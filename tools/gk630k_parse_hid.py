"""Minimal HID report-descriptor parser: prints items, tracking usage pages per collection."""
import sys

# type-ish tables
SIZES = {0:0, 1:1, 2:2, 3:4}
ITEM_TYPES = {0:"Main", 1:"Global", 2:"Local", 3:"Long"}
MAIN = {0x8:"Input",0x9:"Output",0xA:"Collection",0xB:"Feature",0xC:"End"}
GLOBAL = [(0x00,"Usage Page"),(0x01,"Logical Min"),(0x02,"Logical Max"),
          (0x03,"Physical Min"),(0x04,"Physical Max"),(0x05,"Unit Exponent"),
          (0x06,"Unit"),(0x07,"Report Size"),(0x08,"Report ID"),(0x09,"Report Count"),
          (0x0A,"Push"),(0x0B,"Pop")]
LOCAL = [(0x00,"Usage"),(0x01,"Usage Min"),(0x02,"Usage Max"),(0x03,"Designator Index"),
         (0x04,"Designator Min"),(0x05,"Designator Max"),(0x07,"String Index"),
         (0x08,"String Min"),(0x09,"String Max"),(0x0A,"Delimiter")]
COLLECTIONS = {0:"Physical",1:"Application",2:"Logical",3:"Report",4:"Named Array",5:"Usage Switch",6:"Usage Modifier"}

data = bytes.fromhex("".join(sys.argv[1:])) if len(sys.argv)>1 else open(sys.argv[1],"rb").read()
i = 0
state = {}
stack = [{"usage_page":0}]
def fmt(tag, val):
    return f"[{tag}]"
while i < len(data):
    b = data[i]; i += 1
    if b == 0xFE:  # long item
        size = data[i]; tag = data[i+1]; i += 2
        payload = data[i:i+size]; i += size
        print(f"LONG item size={size} tag=0x{tag:02x} data={payload.hex()}")
        continue
    size = SIZES[b & 3]
    payload = data[i:i+size]; i += size
    val = int.from_bytes(payload, "little", signed=True)
    itype, tag = (b >> 2) & 3, (b >> 4) & 0xF
    tname = ITEM_TYPES[itype]
    if tname == "Global":
        name = dict(GLOBAL)[tag]
        state[name] = val
    elif tname == "Local":
        name = dict(LOCAL)[tag]
        state[name] = val
    elif tname == "Main":
        name = MAIN[tag]
        if tag == 0xA:  # collection
            stack.append({"usage_page": state.get("Usage Page",0), "name": COLLECTIONS.get(val, hex(val))})
            print(f"  Collection ({COLLECTIONS.get(val, hex(val))}), usage page 0x{state.get('Usage Page',0):02X}")
            continue
        if tag == 0xC:  # end
            print(f"{state.get('Usage Page',0):02X} End Collection")
            continue
        rid = state.get("Report ID", 0)
        bits = state.get("Report Size",0) * state.get("Report Count",0)
        print(f"{name:8s} UP=0x{state.get('Usage Page',0):02X} Usage(min/max)=0x{state.get('Usage Min', state.get('Usage',0) if isinstance(state.get('Usage'),int) else 0):02X}"
              f"/0x{state.get('Usage Max', state.get('Usage',0) if isinstance(state.get('Usage'),int) else 0):02X}"
              f" size={state.get('Report Size',0)} count={state.get('Report Count',0)} ({bits//8} bytes) ReportID={rid}")
        for n in ("Usage Min","Usage Max"): state.pop(n, None)
        state.pop("Usage", None)
