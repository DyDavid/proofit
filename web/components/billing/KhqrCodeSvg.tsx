"use client";

import React, { useMemo } from "react";

/**
 * Self-contained ISO/IEC 18004 QR Code Byte-Mode (EC Level L, Versions 1..14)
 * encoder for rendering dynamic EMVCo Bakong KHQR strings locally as crisp SVG.
 * Zero external network calls or third-party dependencies.
 */

interface VersionSpec {
  version: number;
  totalCodewords: number;
  ecCodewordsPerBlock: number;
  numBlocksGroup1: number;
  dataCodewordsGroup1: number;
  numBlocksGroup2: number;
  dataCodewordsGroup2: number;
  alignmentCenters: number[];
}

// ISO/IEC 18004 EC Level L table for Versions 1..14 (supports up to 458 UTF-8 bytes)
const VERSION_SPECS_L: VersionSpec[] = [
  { version: 1, totalCodewords: 26, ecCodewordsPerBlock: 7, numBlocksGroup1: 1, dataCodewordsGroup1: 19, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [] },
  { version: 2, totalCodewords: 44, ecCodewordsPerBlock: 10, numBlocksGroup1: 1, dataCodewordsGroup1: 34, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 18] },
  { version: 3, totalCodewords: 70, ecCodewordsPerBlock: 15, numBlocksGroup1: 1, dataCodewordsGroup1: 55, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 22] },
  { version: 4, totalCodewords: 100, ecCodewordsPerBlock: 20, numBlocksGroup1: 1, dataCodewordsGroup1: 80, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 26] },
  { version: 5, totalCodewords: 134, ecCodewordsPerBlock: 26, numBlocksGroup1: 1, dataCodewordsGroup1: 108, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 30] },
  { version: 6, totalCodewords: 172, ecCodewordsPerBlock: 18, numBlocksGroup1: 2, dataCodewordsGroup1: 68, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 34] },
  { version: 7, totalCodewords: 196, ecCodewordsPerBlock: 20, numBlocksGroup1: 2, dataCodewordsGroup1: 78, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 22, 38] },
  { version: 8, totalCodewords: 242, ecCodewordsPerBlock: 24, numBlocksGroup1: 2, dataCodewordsGroup1: 97, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 24, 42] },
  { version: 9, totalCodewords: 292, ecCodewordsPerBlock: 30, numBlocksGroup1: 2, dataCodewordsGroup1: 116, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 26, 46] },
  { version: 10, totalCodewords: 346, ecCodewordsPerBlock: 18, numBlocksGroup1: 2, dataCodewordsGroup1: 68, numBlocksGroup2: 2, dataCodewordsGroup2: 69, alignmentCenters: [6, 28, 50] },
  { version: 11, totalCodewords: 404, ecCodewordsPerBlock: 20, numBlocksGroup1: 4, dataCodewordsGroup1: 81, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 30, 54] },
  { version: 12, totalCodewords: 466, ecCodewordsPerBlock: 24, numBlocksGroup1: 2, dataCodewordsGroup1: 92, numBlocksGroup2: 2, dataCodewordsGroup2: 93, alignmentCenters: [6, 32, 58] },
  { version: 13, totalCodewords: 532, ecCodewordsPerBlock: 26, numBlocksGroup1: 4, dataCodewordsGroup1: 107, numBlocksGroup2: 0, dataCodewordsGroup2: 0, alignmentCenters: [6, 34, 62] },
  { version: 14, totalCodewords: 581, ecCodewordsPerBlock: 30, numBlocksGroup1: 3, dataCodewordsGroup1: 115, numBlocksGroup2: 1, dataCodewordsGroup2: 116, alignmentCenters: [6, 26, 46, 66] },
];

const GF_EXP = new Uint8Array(512);
const GF_LOG = new Uint8Array(256);
(() => {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    GF_EXP[i] = x;
    GF_LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) {
    GF_EXP[i] = GF_EXP[i - 255];
  }
})();

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return GF_EXP[GF_LOG[a] + GF_LOG[b]];
}

function rsGeneratorPoly(degree: number): Uint8Array {
  let poly = new Uint8Array([1]);
  for (let i = 0; i < degree; i++) {
    const next = new Uint8Array(poly.length + 1);
    const root = GF_EXP[i];
    for (let j = 0; j < poly.length; j++) {
      next[j] ^= poly[j];
      next[j + 1] ^= gfMul(poly[j], root);
    }
    poly = next;
  }
  return poly;
}

function rsComputeRemainder(data: Uint8Array, ecLen: number): Uint8Array {
  const gen = rsGeneratorPoly(ecLen);
  const rem = new Uint8Array(ecLen);
  for (let i = 0; i < data.length; i++) {
    const factor = data[i] ^ rem[0];
    rem.copyWithin(0, 1);
    rem[ecLen - 1] = 0;
    if (factor !== 0) {
      for (let j = 0; j < ecLen; j++) {
        rem[j] ^= gfMul(gen[j + 1], factor);
      }
    }
  }
  return rem;
}

export function encodeQrMatrix(payload: string): boolean[][] {
  const utf8 = new TextEncoder().encode(payload);

  // Pick smallest version that fits utf8 in Byte Mode
  let spec: VersionSpec | null = null;
  for (const candidate of VERSION_SPECS_L) {
    const totalDataCodewords =
      candidate.numBlocksGroup1 * candidate.dataCodewordsGroup1 +
      candidate.numBlocksGroup2 * candidate.dataCodewordsGroup2;
    const countBits = candidate.version <= 9 ? 8 : 16;
    const neededBits = 4 + countBits + utf8.length * 8;
    if ( neededBits <= totalDataCodewords * 8) {
      spec = candidate;
      break;
    }
  }
  if (!spec) {
    throw new Error("QR payload exceeds supported length.");
  }

  const totalDataCodewords =
    spec.numBlocksGroup1 * spec.dataCodewordsGroup1 +
    spec.numBlocksGroup2 * spec.dataCodewordsGroup2;

  const bits: number[] = [];
  const pushBits = (val: number, len: number) => {
    for (let i = len - 1; i >= 0; i--) {
      bits.push((val >>> i) & 1);
    }
  };

  // Mode indicator: 0100 (Byte mode)
  pushBits(0b0100, 4);
  pushBits(utf8.length, spec.version <= 9 ? 8 : 16);
  for (let i = 0; i < utf8.length; i++) {
    pushBits(utf8[i], 8);
  }

  // Terminator (up to 4 zero bits)
  const maxBits = totalDataCodewords * 8;
  const term = Math.min(4, maxBits - bits.length);
  pushBits(0, term);

  // Pad to byte boundary
  while (bits.length % 8 !== 0) {
    bits.push(0);
  }

  const dataBytes = new Uint8Array(totalDataCodewords);
  for (let i = 0; i < bits.length / 8; i++) {
    let b = 0;
    for (let j = 0; j < 8; j++) {
      b = (b << 1) | bits[i * 8 + j];
    }
    dataBytes[i] = b;
  }

  const padBytes = [0xec, 0x11];
  let padIdx = 0;
  for (let i = bits.length / 8; i < totalDataCodewords; i++) {
    dataBytes[i] = padBytes[padIdx % 2];
    padIdx++;
  }

  // Split into blocks & compute Reed-Solomon EC codewords
  const dataBlocks: Uint8Array[] = [];
  const ecBlocks: Uint8Array[] = [];
  let offset = 0;

  for (let b = 0; b < spec.numBlocksGroup1; b++) {
    const block = dataBytes.slice(offset, offset + spec.dataCodewordsGroup1);
    offset += spec.dataCodewordsGroup1;
    dataBlocks.push(block);
    ecBlocks.push(rsComputeRemainder(block, spec.ecCodewordsPerBlock));
  }
  for (let b = 0; b < spec.numBlocksGroup2; b++) {
    const block = dataBytes.slice(offset, offset + spec.dataCodewordsGroup2);
    offset += spec.dataCodewordsGroup2;
    dataBlocks.push(block);
    ecBlocks.push(rsComputeRemainder(block, spec.ecCodewordsPerBlock));
  }

  // Interleave data and EC codewords
  const interleaved: number[] = [];
  const maxDataLen = Math.max(spec.dataCodewordsGroup1, spec.dataCodewordsGroup2);
  for (let i = 0; i < maxDataLen; i++) {
    for (const blk of dataBlocks) {
      if (i < blk.length) interleaved.push(blk[i]);
    }
  }
  for (let i = 0; i < spec.ecCodewordsPerBlock; i++) {
    for (const blk of ecBlocks) {
      interleaved.push(blk[i]);
    }
  }

  const size = spec.version * 4 + 17;
  const modules: boolean[][] = Array.from({ length: size }, () =>
    Array<boolean>(size).fill(false),
  );
  const isFunction: boolean[][] = Array.from({ length: size }, () =>
    Array<boolean>(size).fill(false),
  );

  const setFunctionModule = (r: number, c: number, dark: boolean) => {
    if (r < 0 || r >= size || c < 0 || c >= size) return;
    modules[r][c] = dark;
    isFunction[r][c] = true;
  };

  // Finder patterns + separators
  const drawFinder = (topR: number, leftC: number) => {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const r = topR + dr;
        const c = leftC + dc;
        if (r < 0 || r >= size || c < 0 || c >= size) continue;
        const inOuter =
          dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6 &&
          (dr === 0 || dr === 6 || dc === 0 || dc === 6);
        const inInner = dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4;
        setFunctionModule(r, c, inOuter || inInner);
      }
    }
  };
  drawFinder(0, 0);
  drawFinder(0, size - 7);
  drawFinder(size - 7, 0);

  // Timing patterns
  for (let i = 8; i < size - 8; i++) {
    setFunctionModule(6, i, i % 2 === 0);
    setFunctionModule(i, 6, i % 2 === 0);
  }

  // Alignment patterns
  const centers = spec.alignmentCenters;
  for (let i = 0; i < centers.length; i++) {
    for (let j = 0; j < centers.length; j++) {
      if (
        (i === 0 && j === 0) ||
        (i === 0 && j === centers.length - 1) ||
        (i === centers.length - 1 && j === 0)
      ) {
        continue;
      }
      const cr = centers[i];
      const cc = centers[j];
      for (let dr = -2; dr <= 2; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          const dark =
            Math.abs(dr) === 2 || Math.abs(dc) === 2 || (dr === 0 && dc === 0);
          setFunctionModule(cr + dr, cc + dc, dark);
        }
      }
    }
  }

  // Reserve format info areas + dark module
  for (let i = 0; i <= 8; i++) {
    if (i !== 6) {
      setFunctionModule(8, i, false);
      setFunctionModule(i, 8, false);
    }
  }
  for (let i = 0; i < 8; i++) {
    setFunctionModule(8, size - 1 - i, false);
    setFunctionModule(size - 1 - i, 8, false);
  }
  setFunctionModule(size - 8, 8, true);

  // Version info for versions >= 7
  if (spec.version >= 7) {
    let rem = spec.version;
    for (let i = 0; i < 12; i++) {
      rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    }
    const vBits = (spec.version << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const bit = ((vBits >>> i) & 1) !== 0;
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      setFunctionModule(a, b, bit);
      setFunctionModule(b, a, bit);
    }
  }

  // Place data bits in upward/downward 2-column zig-zag
  let bitIdx = 0;
  const totalBits = interleaved.length * 8;
  let upward = true;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      const r = upward ? size - 1 - vert : vert;
      for (let j = 0; j < 2; j++) {
        const c = right - j;
        if (!isFunction[r][c]) {
          let dark = false;
          if (bitIdx < totalBits) {
            const byteVal = interleaved[bitIdx >>> 3];
            dark = ((byteVal >>> (7 - (bitIdx & 7))) & 1) !== 0;
            bitIdx++;
          }
          modules[r][c] = dark;
        }
      }
    }
    upward = !upward;
  }

  // Apply mask 0: (r + c) % 2 === 0
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (!isFunction[r][c] && (r + c) % 2 === 0) {
        modules[r][c] = !modules[r][c];
      }
    }
  }

  // Write format information for EC Level L (01) and Mask 0 (000) -> data = 0b01000
  const formatData = (0b01 << 3) | 0;
  let fRem = formatData;
  for (let i = 0; i < 10; i++) {
    fRem = (fRem << 1) ^ ((fRem >>> 9) * 0x537);
  }
  const formatBits = ((formatData << 10) | fRem) ^ 0x5412;

  const getFormatBit = (idx: number) => ((formatBits >>> idx) & 1) !== 0;

  // Top-left format info: bits 14..0
  for (let i = 0; i <= 5; i++) setFunctionModule(8, i, getFormatBit(14 - i));
  setFunctionModule(8, 7, getFormatBit(8));
  setFunctionModule(8, 8, getFormatBit(7));
  setFunctionModule(7, 8, getFormatBit(6));
  for (let i = 0; i <= 5; i++) setFunctionModule(5 - i, 8, getFormatBit(5 - i));

  // Bottom-left (bits 14..8) and top-right (bits 7..0)
  for (let i = 0; i < 7; i++) setFunctionModule(size - 1 - i, 8, getFormatBit(14 - i));
  for (let i = 0; i < 8; i++) setFunctionModule(8, size - 8 + i, getFormatBit(7 - i));
  setFunctionModule(size - 8, 8, true);

  return modules;
}

export interface KhqrCodeSvgProps {
  qrPayload: string;
  recipientName: string;
  amountDisplay: string;
  currency: string;
  billNumber: string;
}

export function KhqrCodeSvg({
  qrPayload,
  recipientName,
  amountDisplay,
  currency,
  billNumber,
}: KhqrCodeSvgProps) {
  const matrix = useMemo(() => {
    try {
      return encodeQrMatrix(qrPayload);
    } catch {
      return null;
    }
  }, [qrPayload]);

  const quietZone = 4;
  const size = matrix ? matrix.length : 0;
  const viewBoxSize = size + quietZone * 2;

  return (
    <div
      data-testid="bakong-khqr-card"
      className="w-56 shrink-0 overflow-hidden rounded-2xl border border-neutral-200 bg-white text-left shadow-md"
    >
      {/* Official KHQR Red Header */}
      <div className="relative bg-[#E1232E] px-4 py-2.5 text-center">
        <span className="font-mono text-sm font-extrabold tracking-widest text-white">
          KHQR
        </span>
      </div>

      {/* Payee & Amount Section */}
      <div className="border-b border-dashed border-neutral-200 px-4 py-3">
        <p className="truncate font-sans text-xs font-semibold uppercase tracking-wide text-neutral-700">
          {recipientName}
        </p>
        <p className="mt-0.5 font-sans text-xl font-bold text-neutral-900">
          {amountDisplay}{" "}
          <span className="text-xs font-semibold text-neutral-500">
            {currency}
          </span>
        </p>
      </div>

      {/* Dynamic QR Code SVG */}
      <div className="flex flex-col items-center justify-center bg-white p-3">
        {matrix ? (
          <svg
            viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`}
            shapeRendering="crispEdges"
            role="img"
            aria-label={`Dynamic Bakong KHQR for ${recipientName}, ${amountDisplay} ${currency}, bill ${billNumber}`}
            className="h-44 w-44"
          >
            <rect
              x={0}
              y={0}
              width={viewBoxSize}
              height={viewBoxSize}
              fill="#FFFFFF"
            />
            {matrix.map((row, rIdx) =>
              row.map((dark, cIdx) =>
                dark ? (
                  <rect
                    key={`${rIdx}-${cIdx}`}
                    x={cIdx + quietZone}
                    y={rIdx + quietZone}
                    width={1}
                    height={1}
                    fill="#000000"
                  />
                ) : null,
              ),
            )}
          </svg>
        ) : (
          <div className="flex h-48 w-48 items-center justify-center text-xs text-neutral-500">
            Invalid QR payload
          </div>
        )}
      </div>
    </div>
  );
}
