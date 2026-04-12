"use client";

import { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Stars } from "@react-three/drei";
import * as THREE from "three";

// ── Config ────────────────────────────────────────────────────────────────

const RING_RADIUS = 3;
const COLORS = ["#6366f1", "#8b5cf6", "#06b6d4", "#f43f5e", "#f59e0b"];

function lcg(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

// Pre-generated, deterministic — stable between renders
const ORB_CONFIGS = (() => {
  const rng = lcg(77);
  return Array.from({ length: 12 }, (_, i) => ({
    id: i,
    angle: (i / 12) * Math.PI * 2 + (rng() - 0.5) * 0.4,
    color: COLORS[i % COLORS.length],
    radius: 0.16 + rng() * 0.14,
  }));
})();

// ── Ring ──────────────────────────────────────────────────────────────────

function Ring({ isLoading }: { isLoading: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  const speedRef = useRef((Math.PI * 2) / 8);

  useFrame((state, delta) => {
    if (!ref.current) return;
    // Smoothly transition speed: loading=full, done=gentle
    const target = isLoading ? (Math.PI * 2) / 8 : 0.12;
    speedRef.current += (target - speedRef.current) * 0.03;
    ref.current.rotation.z += delta * speedRef.current;

    if (!isLoading) {
      const pulse = 1 + Math.sin(state.clock.elapsedTime * 1.5) * 0.025;
      ref.current.scale.setScalar(pulse);
    } else {
      ref.current.scale.setScalar(1);
    }
  });

  return (
    <mesh ref={ref} rotation={[Math.PI * 0.08, 0, 0]}>
      <torusGeometry args={[RING_RADIUS, 0.032, 16, 128]} />
      <meshStandardMaterial
        color="#6366f1"
        emissive="#6366f1"
        emissiveIntensity={isLoading ? 2.0 : 1.2}
      />
    </mesh>
  );
}

// ── Single orb — scale-pops in on mount ───────────────────────────────────

function OrbMesh({
  config,
}: {
  config: (typeof ORB_CONFIGS)[0];
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const birthRef = useRef<number | null>(null);

  useFrame((state) => {
    if (!meshRef.current) return;
    if (birthRef.current === null) birthRef.current = state.clock.elapsedTime;
    const t = state.clock.elapsedTime - birthRef.current;
    let s: number;
    if (t < 0.15) s = (t / 0.15) * 1.2;
    else if (t < 0.3) s = 1.2 - ((t - 0.15) / 0.15) * 0.2;
    else s = 1.0;
    meshRef.current.scale.setScalar(s);
  });

  return (
    <mesh
      ref={meshRef}
      scale={0}
      position={[
        RING_RADIUS * Math.cos(config.angle),
        RING_RADIUS * Math.sin(config.angle),
        0.06,
      ]}
    >
      <sphereGeometry args={[config.radius, 16, 16]} />
      <meshStandardMaterial
        color={config.color}
        emissive={config.color}
        emissiveIntensity={0.85}
      />
    </mesh>
  );
}

// ── Scene ─────────────────────────────────────────────────────────────────

function Scene({
  isLoading,
  orbCount,
}: {
  isLoading: boolean;
  orbCount: number;
}) {
  const visible = useMemo(() => ORB_CONFIGS.slice(0, orbCount), [orbCount]);

  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight
        position={[0, 0, 6]}
        color="#6366f1"
        intensity={5}
        distance={22}
      />
      <pointLight
        position={[0, 0, -3]}
        color="#8b5cf6"
        intensity={3}
        distance={15}
      />
      <Stars radius={100} depth={50} count={3000} factor={4} fade speed={1} />
      <Ring isLoading={isLoading} />
      {visible.map((cfg) => (
        <OrbMesh key={cfg.id} config={cfg} />
      ))}
    </>
  );
}

// ── Public export ──────────────────────────────────────────────────────────

export default function ScanOrbit({
  isLoading,
  orbCount,
}: {
  isLoading: boolean;
  orbCount: number;
}) {
  return (
    <Canvas
      camera={{ position: [0, 0, 10], fov: 55 }}
      gl={{ antialias: true }}
      dpr={[1, 2]}
    >
      <Scene isLoading={isLoading} orbCount={orbCount} />
    </Canvas>
  );
}
