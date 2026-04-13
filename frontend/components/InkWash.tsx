// frontend/components/InkWash.tsx
export default function InkWash() {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        zIndex: 0,
      }}
    >
      <div className="ink-layer ink-layer-1" />
      <div className="ink-layer ink-layer-2" />
      <div className="ink-layer ink-layer-3" />
      <div className="ink-layer ink-layer-4" />
      <div className="ink-grain" />
    </div>
  );
}
