#!/usr/bin/env python3
"""Slot -> physical position map for the GK630K (matrix col*8+row).
Positions in key units, ISO TKL geometry. Uncertain slots marked None (skipped)."""
# (col,row) -> (name, x, y) ; x,y = key center in units, main grid 17 wide x 6 tall

# rows 0-4: uniform columns (col == physical column), with standard gaps ignored
NAMES = {}
def build():
    m = {}
    # row 0: ESC F1..F12 PRSC SCRL PAUS
    r0 = ['ESC','F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12','PRSC','SCRL','PAUS']
    # row 1: ` 1..0 - = BKSP INS HOME (+PGUP sampled at col16)
    r1 = ['`','1','2','3','4','5','6','7','8','9','0','-','=','BKSP','INS','HOME']
    # row 2: TAB Q..P [ ] \ DEL END (+PGDN sampled at col16)
    r2 = ['TAB','Q','W','E','R','T','Y','U','I','O','P','[',']','\\','DEL','END']
    # row 3: CAPS A..L ; ' # ENTER PGUP PGDN
    r3 = ['CAPS','A','S','D','F','G','H','J','K','L',';',"'",'#','ENTER','PGUP','PGDN']
    # row 4: LSH <> Z..M , . / RSH UP (+phantom col15)
    r4 = ['LSH','<>','Z','X','C','V','B','N','M',',','.','/',None,'RSH','UP',None]
    rows = [r0, r1, r2, r3, r4]
    for row, names in enumerate(rows):
        for col, name in enumerate(names):
            if name is None:
                continue
            m[(col, row)] = (name, col + 0.5, row + 0.5)
    # bottom row by identity (wide keys)
    bottom = {'LCTRL': 0.625, 'WIN': 1.875, 'ALT': 3.125, 'SPACE': 6.875,
              'RALT': 10.625, 'FN': 11.875, 'MENU': 13.125, 'RCTRL': 14.375,
              'LEFT': 13.5, 'DOWN': 14.5, 'RIGHT': 15.5}
    # matrix row5 slots: c0=LCTRL c1=WIN c2=ALT c5=SPACE c11=MENU c12=RALT c13=LEFT c14=DOWN c15=RIGHT
    # c3,c4,c6,c7,c8,c9,c10 = phantoms -> skip
    slotmap = {0: 'LCTRL', 1: 'WIN', 2: 'ALT', 5: 'SPACE', 11: 'MENU', 12: 'RALT',
               13: 'LEFT', 14: 'DOWN', 15: 'RIGHT'}
    for col, name in slotmap.items():
        m[(col, 5)] = (name, bottom[name], 5.5)
    # UP arrow (row4 col14)
    m[(14, 4)] = ('UP', 14.5, 4.5)
    return m

MAP = build()

def slot_pos(slot):
    """(x, y) center in key units, or None to skip."""
    col, row = slot // 8, slot % 8
    if row <= 4:
        return MAP.get((col, row), (None,))[1:] if (col, row) in MAP else None
    if row == 5:
        return MAP.get((col, row), (None,))[1:] if (col, row) in MAP else None
    return None  # rows 6-7 skipped for video
