// frontend/app/dashboard/ChatWindow.tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import ScheduleCard from "./ScheduleCard";
import ConfirmButtons from "./ConfirmButtons";
import NudgeCard, { type NudgeCardData } from "./NudgeCard";

interface Message {
  role: "user" | "assistant";
  content: string;
  schedule_card?: Record<string, unknown> | null;
  nudge?: NudgeCardData | null;
}

function ThinkingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2 }}
      style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0" }}
    >
      <span style={{ color: "var(--text-muted)", fontSize: 13, fontStyle: "italic" }}>
        Papyrus is thinking
      </span>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
          style={{
            width: 4,
            height: 4,
            borderRadius: "50%",
            background: "var(--accent)",
            display: "inline-block",
          }}
        />
      ))}
    </motion.div>
  );
}

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "Good morning. How do you want to approach today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingSchedule, setPendingSchedule] =
    useState<Record<string, unknown> | null>(null);
  const [nudge, setNudge] = useState<NudgeCardData | null>(null);
  const [nudgeShown, setNudgeShown] = useState(false);
  const [token, setToken] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const supabase = createClient();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendMessage = async (content: string) => {
    if (!content.trim() || loading) return;

    const newMessages: Message[] = [
      ...messages,
      { role: "user", content: content.trim() },
    ];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const { data } = await supabase.auth.getSession();
      const sessionToken = data.session?.access_token ?? "";
      setToken(sessionToken);

      const apiMessages = newMessages.map((m) => ({ role: m.role, content: m.content }));

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${sessionToken}`,
          },
          body: JSON.stringify({ messages: apiMessages }),
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Request failed");
      }

      const data2 = await res.json();
      const assistantMsg: Message = {
        role: "assistant",
        content: data2.message,
        schedule_card: data2.schedule_card ?? null,
      };

      setMessages([...newMessages, assistantMsg]);
      if (data2.schedule_card) setPendingSchedule(data2.schedule_card);
      if (data2.nudge && !nudgeShown) {
        setNudge(data2.nudge);
      }
    } catch (err) {
      setMessages([
        ...newMessages,
        { role: "assistant", content: `Something went wrong: ${(err as Error).message}` },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const handleConfirm = () => {
    sendMessage("Looks good, please confirm the schedule.");
    setPendingSchedule(null);
  };

  const handleReject = () => {
    sendMessage("Let me adjust — please regenerate.");
    setPendingSchedule(null);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100dvh",
        maxWidth: 680,
        margin: "0 auto",
        padding: "0 20px",
      }}
    >
      {/* Message list */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          paddingTop: 48,
          paddingBottom: 8,
          scrollbarWidth: "none",
        }}
      >
        <AnimatePresence initial={false}>
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              style={{
                marginBottom: 24,
                display: "flex",
                flexDirection: "column",
                alignItems: msg.role === "user" ? "flex-end" : "flex-start",
              }}
            >
              {msg.role === "assistant" ? (
                <div style={{ maxWidth: "92%" }}>
                  <p
                    style={{
                      color: "var(--text)",
                      fontSize: 15,
                      lineHeight: 1.75,
                      whiteSpace: "pre-wrap",
                      fontStyle: "normal",
                    }}
                  >
                    {msg.content}
                  </p>
                  {msg.schedule_card && (
                    <div style={{ marginTop: 12 }}>
                      <ScheduleCard
                        schedule={
                          msg.schedule_card as unknown as Parameters<
                            typeof ScheduleCard
                          >[0]["schedule"]
                        }
                      />
                      {i === messages.length - 1 && pendingSchedule && (
                        <ConfirmButtons
                          onConfirm={handleConfirm}
                          onReject={handleReject}
                          disabled={loading}
                        />
                      )}
                    </div>
                  )}
                  {/* Coaching nudge — once per session, last assistant message only */}
                  {i === messages.length - 1 && nudge && !nudgeShown && (
                    <div style={{ marginTop: 12 }}>
                      <NudgeCard
                        nudge={nudge}
                        token={token}
                        apiBase={process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
                        onDismiss={() => setNudgeShown(true)}
                        onAction={(label) => {
                          setNudgeShown(true);
                          sendMessage(label);
                        }}
                      />
                    </div>
                  )}
                </div>
              ) : (
                /* User: warm pill on the right */
                <div
                  style={{
                    maxWidth: "72%",
                    padding: "10px 16px",
                    borderRadius: "18px 18px 4px 18px",
                    background: "var(--accent-tint)",
                    border: "1px solid var(--border-strong)",
                    color: "var(--text)",
                    fontSize: 14,
                    lineHeight: 1.6,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {msg.content}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        <AnimatePresence>
          {loading && <ThinkingIndicator />}
        </AnimatePresence>

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div style={{ padding: "12px 0 28px", flexShrink: 0 }}>
        <div
          style={{
            display: "flex",
            gap: 10,
            alignItems: "flex-end",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 16,
            padding: "10px 12px 10px 16px",
          }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
            }}
            onKeyDown={handleKeyDown}
            placeholder="Plan my day, reschedule, or ask anything"
            disabled={loading}
            rows={1}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: "var(--text)",
              fontSize: 14,
              lineHeight: 1.6,
              resize: "none",
              overflow: "hidden",
              fontFamily: "var(--font-literata)",
              paddingTop: 2,
            }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            style={{
              flexShrink: 0,
              width: 34,
              height: 34,
              borderRadius: 10,
              background:
                loading || !input.trim() ? "var(--accent-tint)" : "var(--accent)",
              border: "none",
              cursor: loading || !input.trim() ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "background 0.15s",
              color: loading || !input.trim() ? "var(--accent)" : "var(--bg)",
            }}
            aria-label="Send message"
          >
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <path
                d="M7.5 1.5L7.5 13.5M7.5 1.5L3 6M7.5 1.5L12 6"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
        <p
          style={{
            textAlign: "center",
            color: "var(--text-faint)",
            fontSize: 11,
            marginTop: 8,
          }}
        >
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
