"use client";

import ReactMarkdown from "react-markdown";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, SendHorizonal, Sparkles } from "lucide-react";
import { StockChart } from "./stock-chart";

type ChartRequest = {
  symbol: string;
  period: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  charts?: ChartRequest[];
};

type SimpleChatPanelProps = {
  threadId: string | null;
  onThreadChange?: (threadId: string | null) => void;
  onStreamingChange?: (streaming: boolean) => void;
  onResponseEnd?: () => void;
};

const SUGGESTIONS: { label: string; prompt: string }[] = [
  { label: "个股行情", prompt: "贵州茅台现在股价多少？涨了还是跌了？" },
  { label: "大盘", prompt: "今天大盘怎么样？" },
  { label: "板块", prompt: "白酒板块今天表现如何？" },
  { label: "公告消息", prompt: "宁德时代最近有什么公告消息？" },
  { label: "交易规则", prompt: "A股的手续费是怎么算的？" },
  { label: "加自选", prompt: "把中芯国际加入我的自选股" },
  { label: "画日K", prompt: "画一下比亚迪的日K" },
];

let messageSeq = 0;
function nextId() {
  messageSeq += 1;
  return `m${messageSeq}_${Date.now()}`;
}

const MARKDOWN_COMPONENTS = {
  p: (props: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="mb-2 last:mb-0" {...props} />
  ),
  ul: (props: React.HTMLAttributes<HTMLUListElement>) => (
    <ul className="mb-2 list-disc pl-5" {...props} />
  ),
  ol: (props: React.HTMLAttributes<HTMLOListElement>) => (
    <ol className="mb-2 list-decimal pl-5" {...props} />
  ),
  li: (props: React.LiHTMLAttributes<HTMLLIElement>) => (
    <li className="mb-0.5" {...props} />
  ),
  code: (props: React.HTMLAttributes<HTMLElement>) => (
    <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[12px]" {...props} />
  ),
  table: (props: React.TableHTMLAttributes<HTMLTableElement>) => (
    <table className="my-2 w-full border-collapse text-[12px]" {...props} />
  ),
  th: (props: React.ThHTMLAttributes<HTMLTableCellElement>) => (
    <th className="border border-gray-200 bg-gray-50 px-2 py-1 text-left" {...props} />
  ),
  td: (props: React.TdHTMLAttributes<HTMLTableCellElement>) => (
    <td className="border border-gray-200 px-2 py-1 align-top" {...props} />
  ),
  strong: (props: React.HTMLAttributes<HTMLElement>) => (
    <strong className="font-medium" {...props} />
  ),
};

export function SimpleChatPanel({
  threadId,
  onThreadChange,
  onStreamingChange,
  onResponseEnd,
}: SimpleChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const threadRef = useRef<string | null>(threadId);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    threadRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, status]);

  const send = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (!text || busy) return;

      setInput("");
      setError(null);
      setStatus(null);

      const assistantId = nextId();
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", text },
        { id: assistantId, role: "assistant", text: "", charts: [] },
      ]);

      setBusy(true);
      onStreamingChange?.(true);

      try {
        const response = await fetch("/chat/simple", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: threadRef.current, message: text }),
        });
        if (!response.ok || !response.body) {
          throw new Error(`请求失败：HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() ?? "";

          for (const chunk of chunks) {
            const dataLine = chunk
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (!dataLine) continue;

            let payload: {
              type: string;
              text?: string;
              thread_id?: string;
              message?: string;
              symbol?: string;
              period?: string;
            };
            try {
              payload = JSON.parse(dataLine.slice(6));
            } catch {
              continue;
            }

            if (payload.type === "thread" && payload.thread_id) {
              if (payload.thread_id !== threadRef.current) {
                threadRef.current = payload.thread_id;
                onThreadChange?.(payload.thread_id);
              }
            } else if (payload.type === "delta" && payload.text) {
              const piece = payload.text;
              setMessages((prev) =>
                prev.map((item) =>
                  item.id === assistantId
                    ? { ...item, text: item.text + piece }
                    : item
                )
              );
            } else if (payload.type === "status" && payload.text) {
              setStatus(payload.text);
            } else if (payload.type === "chart" && payload.symbol) {
              const chart: ChartRequest = {
                symbol: payload.symbol,
                period: payload.period ?? "day",
              };
              setMessages((prev) =>
                prev.map((item) =>
                  item.id === assistantId
                    ? { ...item, charts: [...(item.charts ?? []), chart] }
                    : item
                )
              );
            } else if (payload.type === "error" && payload.message) {
              setError(payload.message);
            }
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
        setStatus(null);
        onStreamingChange?.(false);
        onResponseEnd?.();
      }
    },
    [busy, onResponseEnd, onStreamingChange, onThreadChange]
  );

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(input);
    }
  };

  const showSuggestions = messages.length === 0;

  return (
    <div className="flex h-full flex-1 flex-col rounded-xl border border-gray-200 border-t-0 bg-white shadow-sm">
      <div className="flex h-12 items-center justify-between rounded-t-xl bg-blue-600 px-4 text-white">
        <h2 className="text-sm font-semibold sm:text-base lg:text-lg">A股行情助手</h2>
        <span className="flex items-center gap-1 text-[11px] text-blue-100">
          <Sparkles className="h-3 w-3" />
          自研聊天面板
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {showSuggestions && (
          <div className="space-y-3">
            <p className="text-sm text-zinc-600">
              你好，我是 A股行情助手。可以问我个股行情、大盘与板块、公告消息、
              交易规则，也能管理自选股、画 K线 / 分时图。
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => void send(item.prompt)}
                  className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs text-blue-700 transition-colors hover:bg-blue-100"
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-blue-600 px-3.5 py-2 text-sm text-white">
                {message.text}
              </div>
            </div>
          ) : (
            <div key={message.id} className="flex justify-start">
              <div className="max-w-[92%] break-words rounded-2xl rounded-bl-sm border border-gray-200 bg-gray-50 px-3.5 py-2 text-sm text-zinc-800">
                {message.text ? (
                  <ReactMarkdown components={MARKDOWN_COMPONENTS}>
                    {message.text}
                  </ReactMarkdown>
                ) : message.charts?.length ? null : (
                  <span className="text-zinc-400">
                    {busy ? "思考中…" : "（无内容）"}
                  </span>
                )}
                {message.charts?.map((chart, index) => (
                  <StockChart
                    key={`${message.id}-chart-${index}-${chart.symbol}-${chart.period}`}
                    symbol={chart.symbol}
                    period={chart.period}
                  />
                ))}
              </div>
            </div>
          )
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
      </div>

      {status && (
        <div className="flex items-center gap-2 border-t border-gray-100 px-4 py-1.5 text-[11px] text-zinc-500">
          <Loader2 className="h-3 w-3 animate-spin" />
          {status}
        </div>
      )}

      <div className="border-t border-gray-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={busy ? "正在回复…" : "Message... (Enter 发送 / Shift+Enter 换行)"}
            disabled={busy}
            className="max-h-32 min-h-[42px] flex-1 resize-none rounded-xl border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-blue-500 disabled:bg-gray-50"
          />
          <button
            type="button"
            onClick={() => void send(input)}
            disabled={busy || !input.trim()}
            className="flex h-[42px] w-[42px] items-center justify-center rounded-xl bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
            aria-label="发送"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <SendHorizonal className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
