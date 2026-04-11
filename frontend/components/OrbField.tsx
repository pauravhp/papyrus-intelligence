"use client";

import { useRef, useEffect, useState, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Stars, Html, RoundedBox } from "@react-three/drei";
import * as THREE from "three";

// ── Block (calendar event card) definitions ────────────────────────────────

type BlockDef = {
  type: string;
  color: string;
  /** width range represents task duration */
  minW: number;
  maxW: number;
};

// 5 types × varying counts → 16 cards total (4×4 grid)
const BLOCK_DEFS: BlockDef[] = [
  { type: "Deep Work", color: "#6366f1", minW: 2.4, maxW: 3.2 },
  { type: "Meeting",   color: "#8b5cf6", minW: 1.4, maxW: 2.0 },
  { type: "Admin",     color: "#06b6d4", minW: 0.9, maxW: 1.4 },
  { type: "Urgent",    color: "#f43f5e", minW: 1.2, maxW: 1.8 },
  { type: "Event",     color: "#f59e0b", minW: 1.6, maxW: 2.2 },
];

// Sequence of 16 block types laid out across the 4×4 grid (hand-picked for
// colour variety — no two adjacent cells share the same colour)
const GRID_ORDER = [0, 2, 1, 4, 3, 1, 4, 2, 0, 4, 2, 3, 1, 0, 3, 2];

type BlockData = {
  id: number;
  type: string;
  color: string;
  width: number;
  position: [number, number, number];
  rotX: number;
  rotY: number;
  rotZ: number;
  floatSpeed: number;
  floatIntensity: number;
};

// ── Deterministic LCG RNG ──────────────────────────────────────────────────

function makeRng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

// ── Grid-based placement (guaranteed spacing) ─────────────────────────────
//
// Camera: z=14, fov=55 → viewport at z=0 ≈ ±7.3 wide, ±4.1 tall (16:9).
// We divide into a 4×4 grid and place each block in its own cell with random
// jitter, so cards are always spread across the full hero area.

function buildBlocks(isMobile: boolean): BlockData[] {
  const rng = makeRng(17);
  const COLS = 4;
  const ROWS = 4;
  const xHalf = isMobile ? 5.5 : 10.5;
  const yHalf = isMobile ? 3.5 : 5.2;
  const xStep = (xHalf * 2) / COLS;
  const yStep = (yHalf * 2) / ROWS;
  const pad = 0.55; // keep blocks from touching cell edges

  const blocks: BlockData[] = [];
  let id = 0;

  for (let row = 0; row < ROWS; row++) {
    for (let col = 0; col < COLS; col++) {
      const defIdx = GRID_ORDER[id % GRID_ORDER.length];
      const def = BLOCK_DEFS[defIdx];
      const width = def.minW + rng() * (def.maxW - def.minW);

      const cellCx = -xHalf + (col + 0.5) * xStep;
      const cellCy = -yHalf + (row + 0.5) * yStep;

      blocks.push({
        id: id++,
        type: def.type,
        color: def.color,
        width,
        position: [
          cellCx + (rng() * 2 - 1) * (xStep / 2 - pad),
          cellCy + (rng() * 2 - 1) * (yStep / 2 - pad),
          (rng() * 2 - 1) * 3.5 - 0.5, // z depth variation
        ],
        rotX: (rng() * 2 - 1) * 0.2,
        rotY: (rng() * 2 - 1) * 0.25,
        rotZ: (rng() * 2 - 1) * 0.3,
        floatSpeed: 0.7 + rng() * 1.4,
        floatIntensity: 0.2 + rng() * 0.65,
      });
    }
  }
  return blocks;
}

// ── Calendar-event card mesh ───────────────────────────────────────────────

const CARD_H = 0.52;
const CARD_D = 0.1;
const STRIPE_W = 0.07;

function Block({ data }: { data: BlockData }) {
  const [hovered, setHovered] = useState(false);

  return (
    <Float
      speed={data.floatSpeed}
      floatIntensity={data.floatIntensity}
      rotationIntensity={0.2}
    >
      <group
        position={data.position}
        rotation={[data.rotX, data.rotY, data.rotZ]}
      >
        {/* Main card body */}
        <RoundedBox
          args={[data.width, CARD_H, CARD_D]}
          radius={0.07}
          smoothness={4}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHovered(true);
          }}
          onPointerOut={() => setHovered(false)}
        >
          <meshStandardMaterial
            color={data.color}
            emissive={data.color}
            emissiveIntensity={hovered ? 0.7 : 0.35}
            transparent
            opacity={0.82}
            roughness={0.1}
            metalness={0.2}
          />
        </RoundedBox>

        {/* Left accent stripe — mimics Google Calendar event style */}
        <RoundedBox
          args={[STRIPE_W, CARD_H * 0.76, CARD_D + 0.01]}
          radius={0.03}
          smoothness={4}
          position={[-(data.width / 2) + STRIPE_W / 2 + 0.06, 0, 0.005]}
        >
          <meshStandardMaterial
            color={data.color}
            emissive={data.color}
            emissiveIntensity={hovered ? 1.1 : 0.75}
            roughness={0.05}
            metalness={0.1}
          />
        </RoundedBox>

        {/* Hover label */}
        {hovered && (
          <Html center distanceFactor={10}>
            <span
              style={{
                background: "rgba(8,8,16,0.88)",
                color: "#fff",
                fontSize: 12,
                fontFamily: "inherit",
                padding: "4px 10px",
                borderRadius: 6,
                whiteSpace: "nowrap",
                pointerEvents: "none",
                border: "1px solid rgba(255,255,255,0.14)",
              }}
            >
              {data.type}
            </span>
          </Html>
        )}
      </group>
    </Float>
  );
}

// ── Camera parallax on mouse move ─────────────────────────────────────────

function CameraRig({
  mouseRef,
}: {
  mouseRef: { current: { x: number; y: number } };
}) {
  useFrame((state) => {
    state.camera.position.x = THREE.MathUtils.lerp(
      state.camera.position.x,
      mouseRef.current.x * 0.45,
      0.04,
    );
    state.camera.position.y = THREE.MathUtils.lerp(
      state.camera.position.y,
      mouseRef.current.y * 0.3,
      0.04,
    );
    state.camera.lookAt(0, 0, 0);
  });
  return null;
}

// ── Scene ──────────────────────────────────────────────────────────────────

function Scene({
  mouseRef,
  isMobile,
}: {
  mouseRef: { current: { x: number; y: number } };
  isMobile: boolean;
}) {
  const blocks = useMemo(() => buildBlocks(isMobile), [isMobile]);

  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight
        position={[-8, 5, 8]}
        color="#6366f1"
        intensity={7}
        distance={35}
      />
      <pointLight
        position={[8, -4, 6]}
        color="#8b5cf6"
        intensity={5}
        distance={35}
      />
      <Stars radius={100} depth={50} count={3000} factor={4} fade speed={1} />
      {blocks.map((b) => (
        <Block key={b.id} data={b} />
      ))}
      <CameraRig mouseRef={mouseRef} />
    </>
  );
}

// ── Public component ───────────────────────────────────────────────────────

export default function OrbField() {
  const mouseRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    setIsMobile(window.innerWidth < 768);
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      mouseRef.current = {
        x: (e.clientX / window.innerWidth - 0.5) * 2,
        y: -(e.clientY / window.innerHeight - 0.5) * 2,
      };
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  return (
    <Canvas
      camera={{ position: [0, 0, 14], fov: 55 }}
      gl={{ antialias: true }}
      dpr={[1, 2]}
    >
      <Scene mouseRef={mouseRef} isMobile={isMobile} />
    </Canvas>
  );
}
