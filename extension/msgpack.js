// Minimal MessagePack decoder (https://github.com/msgpack/msgpack/blob/master/spec.md).
// Decodes every value type; binary payloads become arrays of byte values and extension
// types become {ext, data} so the result is plain JSON.
(function (root) {
  const utf8 = new TextDecoder("utf-8");

  function decodeAll(input) {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let pos = 0;

    const u8 = () => bytes[pos++];
    const u16 = () => { const v = view.getUint16(pos); pos += 2; return v; };
    const u32 = () => { const v = view.getUint32(pos); pos += 4; return v; };
    const i8 = () => { const v = view.getInt8(pos); pos += 1; return v; };
    const i16 = () => { const v = view.getInt16(pos); pos += 2; return v; };
    const i32 = () => { const v = view.getInt32(pos); pos += 4; return v; };
    const u64 = () => { const v = view.getBigUint64(pos); pos += 8; return big(v); };
    const i64 = () => { const v = view.getBigInt64(pos); pos += 8; return big(v); };
    const f32 = () => { const v = view.getFloat32(pos); pos += 4; return v; };
    const f64 = () => { const v = view.getFloat64(pos); pos += 8; return v; };
    const big = (v) => (v <= BigInt(Number.MAX_SAFE_INTEGER) && v >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(v) : v.toString());
    const str = (n) => { const s = utf8.decode(bytes.subarray(pos, pos + n)); pos += n; return s; };
    const bin = (n) => { const b = Array.from(bytes.subarray(pos, pos + n)); pos += n; return b; };
    const arr = (n) => { const a = new Array(n); for (let i = 0; i < n; i++) a[i] = value(); return a; };
    const map = (n) => { const m = {}; for (let i = 0; i < n; i++) { const k = value(); m[typeof k === "string" ? k : JSON.stringify(k)] = value(); } return m; };
    const ext = (n) => { const type = i8(); return { ext: type, data: bin(n) }; };

    function value() {
      const b = u8();
      if (b <= 0x7f) return b;
      if (b <= 0x8f) return map(b & 0x0f);
      if (b <= 0x9f) return arr(b & 0x0f);
      if (b <= 0xbf) return str(b & 0x1f);
      if (b >= 0xe0) return b - 0x100;
      switch (b) {
        case 0xc0: return null;
        case 0xc2: return false;
        case 0xc3: return true;
        case 0xc4: return bin(u8());
        case 0xc5: return bin(u16());
        case 0xc6: return bin(u32());
        case 0xc7: return ext(u8());
        case 0xc8: return ext(u16());
        case 0xc9: return ext(u32());
        case 0xca: return f32();
        case 0xcb: return f64();
        case 0xcc: return u8();
        case 0xcd: return u16();
        case 0xce: return u32();
        case 0xcf: return u64();
        case 0xd0: return i8();
        case 0xd1: return i16();
        case 0xd2: return i32();
        case 0xd3: return i64();
        case 0xd4: return ext(1);
        case 0xd5: return ext(2);
        case 0xd6: return ext(4);
        case 0xd7: return ext(8);
        case 0xd8: return ext(16);
        case 0xd9: return str(u8());
        case 0xda: return str(u16());
        case 0xdb: return str(u32());
        case 0xdc: return arr(u16());
        case 0xdd: return arr(u32());
        case 0xde: return map(u16());
        case 0xdf: return map(u32());
        default: throw new Error(`invalid MessagePack byte 0x${b.toString(16)} at ${pos - 1}`);
      }
    }

    const values = [];
    while (pos < bytes.length) values.push(value());
    return values;
  }

  root.RobberMsgpack = { decodeAll };
  if (typeof module === "object" && module.exports) module.exports = root.RobberMsgpack;
})(typeof self !== "undefined" ? self : globalThis);
