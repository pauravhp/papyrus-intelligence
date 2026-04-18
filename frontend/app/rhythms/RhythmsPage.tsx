// frontend/app/dashboard/rhythms/RhythmsPage.tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plus } from "lucide-react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import { createClient } from "@/utils/supabase/client";
import { apiFetch, apiPost, apiPatch, apiDelete } from "@/utils/api";
import RhythmCard, { type Rhythm } from "./RhythmCard";
import RhythmPanel, { type RhythmFormData } from "./RhythmPanel";
import RhythmSkeleton from "./RhythmSkeleton";

export default function RhythmsPage() {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;

  const [rhythms, setRhythms] = useState<Rhythm[]>([]);
  const [loading, setLoading] = useState(true);
  const [panelOpen, setPanelOpen] = useState(false);
  const [editingRhythm, setEditingRhythm] = useState<Rhythm | null>(null);

  const getToken = useCallback(async () => {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? "";
  }, [supabase]);

  const loadRhythms = useCallback(
    async (token: string) => {
      const data = await apiFetch<Rhythm[]>("/api/rhythms", token);
      setRhythms(data);
    },
    []
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await getToken();
      if (cancelled) return;
      await loadRhythms(token);
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [getToken, loadRhythms]);

  // DnD
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = rhythms.findIndex((r) => r.id === active.id);
      const newIndex = rhythms.findIndex((r) => r.id === over.id);
      const reordered = arrayMove(rhythms, oldIndex, newIndex);

      // Optimistic update
      setRhythms(reordered);

      const token = await getToken();
      try {
        await Promise.all(
          reordered.map((r, i) =>
            apiPatch<Rhythm>(`/api/rhythms/${r.id}`, { sort_order: i }, token)
          )
        );
      } catch {
        // Revert on failure
        setRhythms(rhythms);
      }
    },
    [rhythms, getToken]
  );

  // Add / Edit save
  const handleSave = useCallback(
    async (data: RhythmFormData) => {
      const token = await getToken();

      if (editingRhythm) {
        const updated = await apiPatch<Rhythm>(
          `/api/rhythms/${editingRhythm.id}`,
          {
            sessions_per_week: data.sessions_per_week,
            session_min: data.session_min,
            session_max: data.session_max,
            end_date: data.end_date || null,
          },
          token
        );
        setRhythms((prev) =>
          prev.map((r) => (r.id === updated.id ? updated : r))
        );
      } else {
        const created = await apiPost<Rhythm>(
          "/api/rhythms",
          {
            name: data.name,
            sessions_per_week: data.sessions_per_week,
            session_min: data.session_min,
            session_max: data.session_max,
            end_date: data.end_date || null,
            sort_order: rhythms.length,
          },
          token
        );
        setRhythms((prev) => [...prev, created]);
      }

      setPanelOpen(false);
      setEditingRhythm(null);
    },
    [editingRhythm, rhythms.length, getToken]
  );

  // Delete (optimistic)
  const handleDelete = useCallback(
    async (id: number) => {
      const snapshot = rhythms;
      setRhythms((prev) => prev.filter((r) => r.id !== id));
      try {
        const token = await getToken();
        await apiDelete(`/api/rhythms/${id}`, token);
      } catch {
        setRhythms(snapshot);
      }
    },
    [rhythms, getToken]
  );

  const openAdd = () => {
    setEditingRhythm(null);
    setPanelOpen(true);
  };

  const openEdit = (rhythm: Rhythm) => {
    setEditingRhythm(rhythm);
    setPanelOpen(true);
  };

  const closePanel = () => {
    setPanelOpen(false);
    setEditingRhythm(null);
  };

  return (
    <div
      style={{
        padding: "40px 48px 64px",
        maxWidth: 768,
      }}
    >
      {/* Page header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 36,
        }}
      >
        <div>
          <h1
            className="font-display"
            style={{
              fontSize: 32,
              fontWeight: 400,
              color: "var(--text)",
              letterSpacing: "-0.01em",
              lineHeight: 1.1,
            }}
          >
            Rhythms
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              fontStyle: "italic",
              marginTop: 4,
            }}
          >
            Your recurring commitments
          </p>
        </div>

        <motion.button
          onClick={openAdd}
          whileHover={{ background: "var(--accent-hover)" }}
          whileTap={{ scale: 0.96 }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            padding: "9px 16px",
            background: "var(--accent)",
            color: "#fff",
            border: "none",
            borderRadius: 9,
            fontFamily: "var(--font-literata)",
            fontSize: 13,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          <Plus size={14} />
          Add rhythm
        </motion.button>
      </div>

      {/* Loading skeletons */}
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[0, 1, 2].map((i) => (
            <RhythmSkeleton key={i} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && rhythms.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          style={{
            paddingTop: 48,
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 10,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 18,
              marginBottom: 4,
            }}
          >
            〜
          </div>
          <h2
            className="font-display"
            style={{ fontSize: 20, fontWeight: 400, color: "var(--text)" }}
          >
            No rhythms yet
          </h2>
          <p
            style={{
              fontSize: 14,
              color: "var(--text-muted)",
              maxWidth: 380,
              lineHeight: 1.65,
              fontStyle: "italic",
            }}
          >
            Rhythms are the commitments you keep with yourself — things like
            exercising three times a week or reading before bed. Add your first
            one to get started.
          </p>
          <motion.button
            onClick={openAdd}
            whileHover={{ background: "var(--accent-tint)" }}
            style={{
              marginTop: 4,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              background: "transparent",
              color: "var(--accent)",
              border: "1px solid var(--border-strong)",
              borderRadius: 8,
              fontFamily: "var(--font-literata)",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <Plus size={13} />
            Add your first rhythm
          </motion.button>
        </motion.div>
      )}

      {/* Card list with DnD */}
      {!loading && rhythms.length > 0 && (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={rhythms.map((r) => r.id)}
            strategy={verticalListSortingStrategy}
          >
            <AnimatePresence initial={false}>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {rhythms.map((rhythm) => (
                  <motion.div
                    key={rhythm.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.2 }}
                  >
                    <RhythmCard
                      rhythm={rhythm}
                      onEdit={openEdit}
                      onDelete={handleDelete}
                    />
                  </motion.div>
                ))}
              </div>
            </AnimatePresence>
          </SortableContext>
        </DndContext>
      )}

      {/* Add/Edit panel */}
      <RhythmPanel
        open={panelOpen}
        rhythm={editingRhythm}
        onClose={closePanel}
        onSave={handleSave}
      />
    </div>
  );
}
