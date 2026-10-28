/**
 * Minimaler ZIP-Schreiber (Methode „stored", ohne Kompression) für den
 * PNG-Frame-Export: PNGs sind bereits komprimiert, Deflate brächte
 * kaum etwas und kostete Zeit. Die Bilder bleiben als Blobs referen-
 * ziert (der Browser darf sie auslagern), nur die Header entstehen neu.
 *
 * Ohne ZIP64: Offsets und Größen sind 32 Bit, darum begrenzt der
 * Aufrufer ein Archiv auf ZIP_PART_LIMIT und beginnt danach ein
 * weiteres (Teil 2, 3, …).
 */

/** Größengrenze je Archiv (deutlich unter 4 GiB, Platz für Header) */
export const ZIP_PART_LIMIT = 3.5 * 1024 ** 3;

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

/** DOS-Datum/-Zeit der Einträge (lokale Zeit, 2-s-Auflösung) */
function dosDateTime(d: Date): [number, number] {
  const time = (d.getHours() << 11) | (d.getMinutes() << 5)
    | (d.getSeconds() >> 1);
  const date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5)
    | d.getDate();
  return [time, date];
}

interface Entry {
  name: Uint8Array;
  crc: number;
  size: number;
  offset: number;
}

export class ZipBuilder {
  private parts: BlobPart[] = [];
  private entries: Entry[] = [];
  private offset = 0;
  private readonly time: number;
  private readonly date: number;

  constructor() {
    [this.time, this.date] = dosDateTime(new Date());
  }

  /** Bisherige Archivgröße in Byte (ohne Zentralverzeichnis) */
  get size(): number { return this.offset; }
  get count(): number { return this.entries.length; }

  async add(name: string, data: Blob): Promise<void> {
    const bytes = new Uint8Array(await data.arrayBuffer());
    const entry: Entry = {
      name: new TextEncoder().encode(name),
      crc: crc32(bytes),
      size: bytes.length,
      offset: this.offset,
    };
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true);     // Local file header
    h.setUint16(4, 20, true);             // benötigte Version 2.0
    h.setUint16(6, 0x0800, true);         // UTF-8-Namen
    h.setUint16(8, 0, true);              // stored
    h.setUint16(10, this.time, true);
    h.setUint16(12, this.date, true);
    h.setUint32(14, entry.crc, true);
    h.setUint32(18, entry.size, true);
    h.setUint32(22, entry.size, true);
    h.setUint16(26, entry.name.length, true);
    h.setUint16(28, 0, true);
    this.parts.push(h.buffer, entry.name, data);
    this.offset += 30 + entry.name.length + entry.size;
    this.entries.push(entry);
  }

  /** Zentralverzeichnis anhängen und Archiv als Blob liefern. */
  finish(): Blob {
    const dirStart = this.offset;
    let dirSize = 0;
    const dir: BlobPart[] = [];
    for (const e of this.entries) {
      const c = new DataView(new ArrayBuffer(46));
      c.setUint32(0, 0x02014b50, true);   // Central directory header
      c.setUint16(4, 20, true);
      c.setUint16(6, 20, true);
      c.setUint16(8, 0x0800, true);
      c.setUint16(10, 0, true);
      c.setUint16(12, this.time, true);
      c.setUint16(14, this.date, true);
      c.setUint32(16, e.crc, true);
      c.setUint32(20, e.size, true);
      c.setUint32(24, e.size, true);
      c.setUint16(28, e.name.length, true);
      // Extra, Kommentar, Disk, Attribute: 0
      c.setUint32(42, e.offset, true);
      dir.push(c.buffer, e.name);
      dirSize += 46 + e.name.length;
    }
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);   // End of central directory
    end.setUint16(8, this.entries.length, true);
    end.setUint16(10, this.entries.length, true);
    end.setUint32(12, dirSize, true);
    end.setUint32(16, dirStart, true);
    return new Blob([...this.parts, ...dir, end.buffer],
                    { type: "application/zip" });
  }
}
