/*
 * mpv video output driver: renders video on an SPC Gear GK630K
 * (Evision 3299:4E5A) keyboard's per-key RGB LEDs.
 *
 * Protocol: Evision vendor reports on HID interface 1, report ID 4,
 * 64-byte packets [04, cksum_lo, cksum_hi, cmd, size, off_lo, off_hi, 00, data].
 * Frames stream with CMD_SEND_FRAME (0x12) in 56-byte chunks and close with
 * CMD_END_FRAME (0x13). RAM only, no EEPROM wear.
 *
 * This file is part of mpv. Licensed under LGPL-2.1-or-later, like mpv.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/select.h>

#include <libswscale/swscale.h>

#include "options/m_config.h"
#include "config.h"
#include "osdep/timer.h"
#include "vo.h"
#include "video/sws_utils.h"
#include "video/mp_image.h"

#include "vo_rgb_keyboard_map.h"

#define IMGFMT IMGFMT_RGB24

#define KB_W 128
#define KB_H 64

#define VID 0x3299
#define PID 0x4E5A

#define REPORT_ID 0x04
#define PACKET_SIZE 64
#define HEADER_SIZE 8
#define CHUNK_SIZE 56
#define FRAME_SIZE (128 * 3)

#define CMD_SEND_FRAME 0x12
#define CMD_END_FRAME 0x13

struct vo_rgb_keyboard_opts {
    char *device;   // hidraw path, empty = auto-detect
    int max_fps;    // stream at most this many frames per second
};

struct priv {
    struct vo_rgb_keyboard_opts opts;
    int fd;
    int64_t last_frame_us;
    int swidth;
    int sheight;
    struct mp_image *frame;
    struct mp_sws_context *sws;
};

static int find_hidraw(char *out, size_t outlen)
{
    DIR *d = opendir("/sys/class/hidraw");
    if (!d)
        return -1;
    struct dirent *e;
    int found = -1;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.')
            continue;
        char path[256], phys[256] = "", id[256] = "";
        FILE *f;
        snprintf(path, sizeof(path), "/sys/class/hidraw/%s/device/uevent", e->d_name);
        f = fopen(path, "r");
        if (!f)
            continue;
        char line[256];
        while (fgets(line, sizeof(line), f)) {
            if (sscanf(line, "HID_ID=%255s", id) == 1)
                continue;
            if (sscanf(line, "HID_PHYS=%255s", phys) == 1)
                continue;
        }
        fclose(f);
        unsigned int bus, vid, pid;
        if (sscanf(id, "%x:%x:%x", &bus, &vid, &pid) == 3 &&
            vid == VID && pid == PID && strstr(phys, "input1")) {
            snprintf(out, outlen, "/dev/%s", e->d_name);
            found = 0;
            break;
        }
    }
    closedir(d);
    return found;
}

static void kb_drain(struct priv *p)
{
    unsigned char tmp[PACKET_SIZE];
    for (;;) {
        fd_set rfds;
        struct timeval tv = {0, 0};
        FD_ZERO(&rfds);
        FD_SET(p->fd, &rfds);
        if (select(p->fd + 1, &rfds, NULL, NULL, &tv) <= 0)
            break;
        if (read(p->fd, tmp, sizeof(tmp)) <= 0)
            break;
    }
}

// Send one vendor command packet, wait for the echo reply. Returns 0 on success.
static int kb_query(struct vo *vo, uint8_t cmd, uint16_t offset,
                    const unsigned char *data, int size)
{
    struct priv *p = vo->priv;
    unsigned char pkt[PACKET_SIZE] = {0};
    pkt[0] = REPORT_ID;
    pkt[3] = cmd;
    pkt[4] = size;
    pkt[5] = offset & 0xFF;
    pkt[6] = (offset >> 8) & 0xFF;
    if (size && data)
        memcpy(pkt + HEADER_SIZE, data, size);
    unsigned int ck = 0;
    for (int i = 3; i < PACKET_SIZE; i++)
        ck += pkt[i];
    pkt[1] = ck & 0xFF;
    pkt[2] = (ck >> 8) & 0xFF;

    kb_drain(p);
    if (write(p->fd, pkt, sizeof(pkt)) != sizeof(pkt)) {
        MP_ERR(vo, "hidraw write failed: %s\n", strerror(errno));
        return -1;
    }
    int64_t deadline = mp_time_ns() / 1000 + 150000;
    for (;;) {
        int64_t now = mp_time_ns() / 1000;
        if (now >= deadline) {
            MP_ERR(vo, "no reply to command 0x%02x\n", cmd);
            return -1;
        }
        fd_set rfds;
        struct timeval tv;
        int64_t usec = deadline - now;
        tv.tv_sec = usec / 1000000;
        tv.tv_usec = usec % 1000000;
        FD_ZERO(&rfds);
        FD_SET(p->fd, &rfds);
        if (select(p->fd + 1, &rfds, NULL, NULL, &tv) <= 0)
            continue;
        unsigned char resp[PACKET_SIZE];
        ssize_t n = read(p->fd, resp, sizeof(resp));
        if (n == sizeof(resp) && resp[0] == REPORT_ID && resp[3] == cmd &&
            (resp[5] | (resp[6] << 8)) == offset)
            return 0;
    }
}

static int kb_send_frame(struct vo *vo, const unsigned char *frame)
{
    struct priv *p = vo->priv;
    for (int pos = 0; pos < FRAME_SIZE; pos += CHUNK_SIZE) {
        if (kb_query(vo, CMD_SEND_FRAME, pos, frame + pos, CHUNK_SIZE) < 0)
            return -1;
    }
    return 0;
}

static void sample_frame(const unsigned char *src, int stride, unsigned char *out)
{
    memset(out, 0, FRAME_SIZE);
    for (int i = 0; i < RGBKB_NUM_KEYS; i++) {
        int s = rgbkb_keys[i].slot;
        long r = 0, g = 0, b = 0, n = 0;
        for (int y = rgbkb_keys[i].y0; y < rgbkb_keys[i].y1; y++) {
            const unsigned char *row = src + y * stride;
            for (int x = rgbkb_keys[i].x0; x < rgbkb_keys[i].x1; x++) {
                r += row[x * 3 + 0];
                g += row[x * 3 + 1];
                b += row[x * 3 + 2];
                n++;
            }
        }
        if (n) {
            out[s * 3 + 0] = r / n;
            out[s * 3 + 1] = g / n;
            out[s * 3 + 2] = b / n;
        }
    }
}

static int reconfig(struct vo *vo, struct mp_image_params *params)
{
    struct priv *p = vo->priv;

    vo->dwidth = KB_W;
    vo->dheight = KB_H;

    p->sws->src = *params;
    p->sws->dst = (struct mp_image_params) {
        .imgfmt = IMGFMT,
        .w = KB_W,
        .h = KB_H,
        .p_w = 1,
        .p_h = 1,
    };

    if (p->frame)
        talloc_free(p->frame);
    p->frame = mp_image_alloc(IMGFMT, KB_W, KB_H);
    if (!p->frame)
        return -1;

    if (mp_sws_reinit(p->sws) < 0)
        return -1;
    return 0;
}

static bool draw_frame(struct vo *vo, struct vo_frame *frame)
{
    struct priv *p = vo->priv;
    struct mp_image *src = frame->current;
    if (!src)
        return VO_TRUE;

    int64_t now = mp_time_ns() / 1000;
    int64_t min_interval = p->opts.max_fps > 0 ? 1000000 / p->opts.max_fps : 0;
    if (min_interval && now - p->last_frame_us < min_interval)
        return VO_TRUE; // throttle: drop, keep playing smoothly

    mp_sws_scale(p->sws, p->frame, src);

    unsigned char rgb[FRAME_SIZE];
    sample_frame(p->frame->planes[0], p->frame->stride[0], rgb);
    if (kb_send_frame(vo, rgb) == 0)
        p->last_frame_us = now;
    return VO_TRUE;
}

static void flip_page(struct vo *vo)
{
    // frames go out in draw_frame; nothing to present
}

static void uninit(struct vo *vo)
{
    struct priv *p = vo->priv;
    if (p->fd >= 0) {
        kb_query(vo, CMD_END_FRAME, 0, NULL, 0);
        close(p->fd);
        p->fd = -1;
    }
    talloc_free(p->frame);
    p->frame = NULL;
}

static int preinit(struct vo *vo)
{
    struct priv *p = vo->priv;
    p->fd = -1;
    p->last_frame_us = 0;

    char path[256];
    if (p->opts.device && p->opts.device[0]) {
        snprintf(path, sizeof(path), "%s", p->opts.device);
    } else if (find_hidraw(path, sizeof(path)) < 0) {
        MP_FATAL(vo, "GK630K keyboard not found (USB %04x:%04x). "
                 "Is it plugged in by cable? See --vo=rgb-keyboard=device=...\n",
                 VID, PID);
        return -1;
    }
    p->fd = open(path, O_RDWR | O_NONBLOCK);
    if (p->fd < 0) {
        MP_FATAL(vo, "cannot open %s: %s (udev rule / permissions?)\n",
                 path, strerror(errno));
        return -1;
    }
    MP_INFO(vo, "streaming to %s\n", path);

    p->sws = mp_sws_alloc(vo);
    p->sws->log = vo->log;
    mp_sws_enable_cmdline_opts(p->sws, vo->global);
    return 0;
}

static int query_format(struct vo *vo, int format)
{
    return format == IMGFMT;
}

static int control(struct vo *vo, uint32_t request, void *data)
{
    if (request == VOCTRL_CHECK_EVENTS)
        return VO_TRUE;
    return VO_NOTIMPL;
}

#define OPT_BASE_STRUCT struct priv

const struct vo_driver video_out_rgb_keyboard = {
    .name = "rgb-keyboard",
    .description = "SPC Gear GK630K per-key RGB LEDs",
    .preinit = preinit,
    .query_format = query_format,
    .reconfig = reconfig,
    .control = control,
    .draw_frame = draw_frame,
    .flip_page = flip_page,
    .uninit = uninit,
    .priv_size = sizeof(struct priv),
    .priv_defaults = &(const struct priv) {
        .opts.max_fps = 30,
    },
    .options = (const m_option_t[]) {
        {"device", OPT_STRING(opts.device)},
        {"max-fps", OPT_INT(opts.max_fps)},
        {0}
    },
    .options_prefix = "vo-rgb-keyboard",
};
