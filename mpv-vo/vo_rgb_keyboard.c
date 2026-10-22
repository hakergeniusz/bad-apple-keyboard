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
#include <signal.h>
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
    double brightness; // 0.0-1.0 global brightness scale
};

struct priv {
    struct vo_rgb_keyboard_opts opts;
    int fd;
    char path[256];
    int fails;
    int64_t last_frame_us;
    int swidth;
    int sheight;
    struct mp_image *frame;
    struct mp_sws_context *sws;
};

// The firmware stays in RGB frame-streaming mode until it receives
// CMD_END_FRAME.  If mpv is killed with SIGKILL (or crashes) the normal
// uninit() path never runs, and the keyboard is left streaming - which
// wedges its firmware key state (the host then sees a phantom key repeating
// forever).  A signal handler cannot do the full write/read handshake
// safely, so it only writes the 64-byte END_FRAME packet asynchronously;
// the kernel guarantees the write is delivered.
//
// mpv installs its own SIGINT/SIGTERM/SIGQUIT handlers (terminal-unix.c) to
// request a graceful shutdown, so we chain to the previous handler instead of
// replacing it - otherwise mpv would never exit.  mpv only installs them
// when it owns the terminal (terminal_setup_getch), so the previous
// disposition can also be SIG_DFL: in that case we must re-raise the signal
// with the default action, otherwise the signal would be swallowed and mpv
// would keep running.
//
// The END_FRAME packet is a constant (checksum = sum of bytes 3..63 = 0x13),
// so the handler only has to write() it - fully async-signal-safe.
static volatile sig_atomic_t kb_endframe_fd = -1;

static const unsigned char kb_endframe_pkt[PACKET_SIZE] = {
    REPORT_ID, 0x13, 0x00, CMD_END_FRAME, 0x00, 0x00, 0x00, 0x00,
};

static struct sigaction kb_prev_sa[4];
static int kb_prev_sa_valid = 0;
static const int kb_sig_nums[4] = {SIGINT, SIGTERM, SIGHUP, SIGQUIT};

// Restore the default disposition and re-raise, so the process dies exactly
// as it would have without our handler installed.
static void kb_sig_default_action(int sig)
{
    struct sigaction sa;
    sa.sa_handler = SIG_DFL;
    sa.sa_flags = 0;
    sigemptyset(&sa.sa_mask);
    sigaction(sig, &sa, NULL);
    raise(sig);
}

static void kb_sig_end_frame(int sig)
{
    int fd = (int)kb_endframe_fd;
    if (fd >= 0) {
        ssize_t r = write(fd, kb_endframe_pkt, sizeof(kb_endframe_pkt));
        (void)r;
    }
    // Chain to whatever mpv had installed before us.
    if (!kb_prev_sa_valid)
        return;
    for (int i = 0; i < 4; i++) {
        if (kb_sig_nums[i] != sig)
            continue;
        const struct sigaction *prev = &kb_prev_sa[i];
        if (prev->sa_flags & SA_SIGINFO) {
            if (prev->sa_sigaction &&
                prev->sa_sigaction !=
                    (void (*)(int, siginfo_t *, void *))kb_sig_end_frame)
                prev->sa_sigaction(sig, NULL, NULL);
            else if (!prev->sa_sigaction)
                kb_sig_default_action(sig);
        } else if (prev->sa_handler == (void (*)(int))kb_sig_end_frame) {
            // We captured our own handler (VO re-created): do not recurse.
            kb_sig_default_action(sig);
        } else if (prev->sa_handler == SIG_IGN) {
            // Explicitly ignored before us: keep ignoring it.
        } else if (!prev->sa_handler || prev->sa_handler == SIG_DFL) {
            kb_sig_default_action(sig);
        } else {
            prev->sa_handler(sig);
        }
        return;
    }
}

// Install our handler, remembering the previous disposition.  Only the first
// installation may capture the previous actions - a second preinit() would
// otherwise capture our own handler and recurse forever.
static void kb_install_signal_handlers(struct vo *vo)
{
    if (kb_prev_sa_valid)
        return;
    for (int i = 0; i < 4; i++) {
        struct sigaction sa;
        sa.sa_handler = kb_sig_end_frame;
        sa.sa_flags = SA_RESTART;
        sigemptyset(&sa.sa_mask);
        sigaction(kb_sig_nums[i], &sa, &kb_prev_sa[i]);
        MP_VERBOSE(vo, "signal %d: previous handler %s\n", kb_sig_nums[i],
                   kb_prev_sa[i].sa_handler == SIG_DFL ? "SIG_DFL" :
                   kb_prev_sa[i].sa_handler == SIG_IGN ? "SIG_IGN" : "custom");
    }
    kb_prev_sa_valid = 1;
}

// Put back the dispositions we replaced (only if they are still ours).
static void kb_restore_signal_handlers(void)
{
    if (!kb_prev_sa_valid)
        return;
    for (int i = 0; i < 4; i++) {
        struct sigaction cur;
        if (sigaction(kb_sig_nums[i], NULL, &cur) == 0 &&
            !(cur.sa_flags & SA_SIGINFO) &&
            cur.sa_handler == (void (*)(int))kb_sig_end_frame)
            sigaction(kb_sig_nums[i], &kb_prev_sa[i], NULL);
    }
    kb_prev_sa_valid = 0;
}

// HID_PHYS looks like "usb-0000:00:14.0-5/input1"; return the input index
// (the trailing number), or -1 if there is none.
static int phys_input_index(const char *phys)
{
    const char *p = strstr(phys, "/input");
    if (!p)
        return -1;
    p += 6;
    if (*p < '0' || *p > '9')
        return -1;
    int n = 0;
    while (*p >= '0' && *p <= '9')
        n = n * 10 + (*p++ - '0');
    return n;
}

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
        char path[512], phys[256] = "", id[256] = "";
        FILE *f;
        snprintf(path, sizeof(path), "/sys/class/hidraw/%.128s/device/uevent",
                 e->d_name);
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
            vid == VID && pid == PID && phys_input_index(phys) == 1) {
            snprintf(out, outlen, "/dev/%.*s",
                     (int)(outlen > 6 ? outlen - 6 : 0), e->d_name);
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
static int kb_open(struct vo *vo, const char *path)
{
    struct priv *p = vo->priv;
    int fd = open(path, O_RDWR | O_NONBLOCK);
    if (fd < 0) {
        MP_ERR(vo, "cannot open %s: %s\n", path, strerror(errno));
        return -1;
    }
    p->fd = fd;
    p->fails = 0;
    kb_endframe_fd = fd;
    return 0;
}

// Reopen after a stall/reset (firmware bootloops recycle the hidraw node).
static int kb_reopen(struct vo *vo)
{
    struct priv *p = vo->priv;
    if (p->fd >= 0) {
        close(p->fd);
        p->fd = -1;
        kb_endframe_fd = -1;
    }
    // node may briefly vanish during re-enumeration; retry a few times
    for (int i = 0; i < 20; i++) {
        if (kb_open(vo, p->path) == 0) {
            MP_WARN(vo, "reopened %s after error\n", p->path);
            // stale node? re-detect by VID/PID
            return 0;
        }
        if (find_hidraw(p->path, sizeof(p->path)) == 0)
            continue;
        usleep(200000);
    }
    MP_ERR(vo, "keyboard gone, giving up\n");
    return -1;
}

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

    for (int attempt = 0; attempt < 2; attempt++) {
        if (p->fd < 0 && kb_reopen(vo) < 0)
            return -1;
        kb_drain(p);
        if (write(p->fd, pkt, sizeof(pkt)) != sizeof(pkt)) {
            MP_DBG(vo, "hidraw write failed: %s\n", strerror(errno));
            close(p->fd);
            p->fd = -1;
            kb_endframe_fd = -1;
            continue;
        }
        int64_t deadline = mp_time_ns() / 1000 + 150000;
        for (;;) {
            int64_t now = mp_time_ns() / 1000;
            if (now >= deadline)
                break;
            fd_set rfds;
            struct timeval tv;
            int64_t usec = deadline - now;
            tv.tv_sec = usec / 1000000;
            tv.tv_usec = usec % 1000000;
            FD_ZERO(&rfds);
            FD_SET(p->fd, &rfds);
            int r = select(p->fd + 1, &rfds, NULL, NULL, &tv);
            if (r < 0) {
                close(p->fd);
                p->fd = -1;
                kb_endframe_fd = -1;
                break;
            }
            if (r == 0)
                continue;
            unsigned char resp[PACKET_SIZE];
            ssize_t n = read(p->fd, resp, sizeof(resp));
            if (n < 0) {
                close(p->fd);
                p->fd = -1;
                kb_endframe_fd = -1;
                break;
            }
            if (n == sizeof(resp) && resp[0] == REPORT_ID && resp[3] == cmd &&
                (resp[5] | (resp[6] << 8)) == offset) {
                p->fails = 0;
                return 0;
            }
        }
        // timeout: drop stale fd, retry once via reopen
        if (p->fd >= 0) {
            close(p->fd);
            p->fd = -1;
            kb_endframe_fd = -1;
        }
    }
    if (++p->fails == 1 || p->fails % 30 == 0)
        MP_WARN(vo, "no reply to command 0x%02x (keyboard resetting?)\n", cmd);
    return -1;
}

static int kb_send_frame(struct vo *vo, const unsigned char *frame)
{
    for (int pos = 0; pos < FRAME_SIZE; pos += CHUNK_SIZE) {
        int n = FRAME_SIZE - pos;
        if (n > CHUNK_SIZE)
            n = CHUNK_SIZE;
        if (kb_query(vo, CMD_SEND_FRAME, pos, frame + pos, n) < 0)
            return -1;
    }
    return 0;
}

static void sample_frame(const unsigned char *src, int stride, unsigned char *out,
                         double brightness)
{
    memset(out, 0, FRAME_SIZE);
    if (brightness < 0)
        brightness = 0;
    if (brightness > 1)
        brightness = 1;
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
            out[s * 3 + 0] = (r / n) * brightness;
            out[s * 3 + 1] = (g / n) * brightness;
            out[s * 3 + 2] = (b / n) * brightness;
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
    sample_frame(p->frame->planes[0], p->frame->stride[0], rgb,
                 p->opts.brightness);
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
    kb_restore_signal_handlers();
    if (p->fd >= 0) {
        kb_query(vo, CMD_END_FRAME, 0, NULL, 0);
        close(p->fd);
        p->fd = -1;
    }
    kb_endframe_fd = -1;
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
                 "Is it plugged in by cable? "
                 "See --vo-rgb-keyboard-device=/dev/hidrawN\n",
                 VID, PID);
        return -1;
    }
    snprintf(p->path, sizeof(p->path), "%s", path);
    if (kb_open(vo, p->path) < 0) {
        MP_FATAL(vo, "cannot open %s (udev rule / permissions?)\n", p->path);
        return -1;
    }
    MP_INFO(vo, "streaming to %s\n", p->path);

    // Make sure the keyboard leaves RGB streaming mode even if mpv is
    // killed with SIGINT/SIGTERM (see kb_sig_end_frame).  We chain to
    // mpv's own handlers so graceful shutdown still works.
    kb_install_signal_handlers(vo);

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
        .opts.brightness = 1.0,
    },
    .options = (const m_option_t[]) {
        {"device", OPT_STRING(opts.device)},
        {"max-fps", OPT_INT(opts.max_fps)},
        {"brightness", OPT_DOUBLE(opts.brightness)},
        {0}
    },
    .options_prefix = "vo-rgb-keyboard",
};
