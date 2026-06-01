import { useState, useRef, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { MessageCircle, X } from "lucide-react";
import { apiPost } from "@/lib/api";

interface Message {
  id: string;
  text: string;
  sender: "user" | "bot";
  timestamp: Date;
  sql?: string;        // optional: show SQL used
  rowCount?: number;   // optional: show result count
}

export default function Chatbot() {
  const location = useLocation();

  const [isOpen, setIsOpen] = useState(() => {
    return localStorage.getItem("chatbot_open") === "true";
  });
  const [messages, setMessages] = useState<Message[]>(() => {
    const saved = localStorage.getItem("chat_history");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        return parsed.map((m: any) => ({
          ...m,
          timestamp: new Date(m.timestamp)
        }));
      } catch (e) {
        console.error("Failed to parse chat history", e);
      }
    }
    return [
      {
        id: "1",
        text: "Hey! 👋 Ask me anything about the surveillance system — I can query the database for you!",
        sender: "bot",
        timestamp: new Date(),
      },
    ];
  });

  useEffect(() => {
    localStorage.setItem("chat_history", JSON.stringify(messages));
  }, [messages]);

  useEffect(() => {
    localStorage.setItem("chatbot_open", isOpen.toString());
  }, [isOpen]);

  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    messagesEndRef.current?.scrollIntoView({ behavior });
  };

  const isInitialMount = useRef(true);

  useEffect(() => {
    if (isOpen) {
      // Use a small timeout to ensure DOM is ready
      const timer = setTimeout(() => {
        scrollToBottom(isInitialMount.current ? "auto" : "smooth");
        if (isInitialMount.current) isInitialMount.current = false;
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isOpen, messages]);

  const handleSend = async () => {
    if (!input.trim()) return;

    const question = input.trim();

    const userMessage: Message = {
      id: Date.now().toString(),
      text: question,
      sender: "user",
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setIsTyping(true);

    const history = messages.map(m => ({
      role: m.sender === "user" ? "user" : "assistant",
      content: m.text,
      sql: m.sql
    }));

    try {
      const result = await apiPost<any>("/api/chatbot/query", { 
        question, 
        history 
      });

      const botMessage: Message = {
        id: (Date.now() + 1).toString(),
        text: result.success
          ? result.answer || "Query executed successfully."
          : `❌ Error: ${result.error || "Something went wrong."}`,
        sender: "bot",
        timestamp: new Date(),
        sql: result.sql,
        rowCount: result.results?.length,
      };

      setMessages(prev => [...prev, botMessage]);
    } catch (err: any) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        text: "❌ Failed to reach the chatbot service. Please try again.",
        sender: "bot",
        timestamp: new Date(),
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (location.pathname === "/login") return null;

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{
            backdropFilter: "blur(40px)",
            background: "rgba(0,0,0,0.8)",
            display: isOpen ? "flex" : "none",  // ← just hide, don't destroy
          }}
          onClick={() => setIsOpen(false)}
        >
          <div
            className="anomaly-rules-page page-bg-grid w-full max-w-2xl h-[80vh] flex flex-col shadow-2xl animate-in fade-in zoom-in duration-200"
            style={{
              minHeight: 'auto',
              borderRadius: '12px',
              border: '1px solid rgba(46,213,115,0.13)',
              background: 'transparent',
              position: 'relative'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="co tl" style={{ zIndex: 1 }}></div>
            <div className="co tr" style={{ zIndex: 1 }}></div>
            <div className="co bl" style={{ zIndex: 1 }}></div>
            <div className="co br" style={{ zIndex: 1 }}></div>

            <div className="right-panel" style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              padding: 0,
              overflow: 'hidden',
              background: 'radial-gradient(circle at top right, rgba(46,213,115,0.06), transparent 500px), rgba(15, 18, 15, 0.7)',
              backdropFilter: 'blur(30px)',
              borderRadius: '12px'
            }}>

              {/* Header */}
              <div className="px-6 py-4 border-b border-[rgba(46,213,115,0.08)] bg-[rgba(0,0,0,0.4)] flex justify-between items-center z-10">
                <h2 className="text-xl font-bold font-['Montserrat'] text-white">
                  Chatbot <span style={{ color: 'rgb(46,213,115)' }}>Assistant</span>
                </h2>
                <button onClick={() => setIsOpen(false)} className="text-[rgba(46,213,115,0.6)] hover:text-white transition-colors p-1">
                  <X className="w-6 h-6" />
                </button>
              </div>

              {/* Messages */}
              <div className="flex-1 p-6 overflow-y-auto flex flex-col space-y-4 z-10" style={{
                scrollbarWidth: 'thin',
                scrollbarColor: 'rgba(46,213,115,0.2) rgba(46,213,115,0.03)'
              }}>
                {messages.map((message) => (
                  <div key={message.id} className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[80%] rounded-xl px-4 py-3 text-[14px] shadow-sm font-['Inter',system-ui] ${message.sender === "user"
                      ? "bg-[rgba(46,213,115,0.1)] text-white border border-[rgba(46,213,115,0.3)]"
                      : "bg-[rgba(255,255,255,0.03)] text-[rgba(255,255,255,0.9)] border border-[rgba(255,255,255,0.08)]"
                      }`}>
                      <p style={{ whiteSpace: 'pre-wrap' }}>{message.text}</p>

                      {/* Show SQL if available */}
                      {message.sql && (
                        <details style={{ marginTop: '8px' }}>
                          <summary style={{
                            color: 'rgba(46,213,115,0.6)',
                            fontSize: '11px',
                            cursor: 'pointer',
                            userSelect: 'none'
                          }}>
                            🔍 View SQL {message.rowCount !== undefined ? `· ${message.rowCount} rows` : ''}
                          </summary>
                          <pre style={{
                            marginTop: '6px',
                            padding: '8px',
                            background: 'rgba(0,0,0,0.4)',
                            borderRadius: '6px',
                            fontSize: '11px',
                            color: 'rgba(255,255,255,0.6)',
                            overflowX: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-all'
                          }}>
                            {message.sql}
                          </pre>
                        </details>
                      )}

                      <p className={`text-[10px] mt-1.5 text-right ${message.sender === "user" ? "text-[rgba(46,213,115,0.7)]" : "text-[rgba(255,255,255,0.4)]"
                        }`}>
                        {message.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </p>
                    </div>
                  </div>
                ))}

                {isTyping && (
                  <div className="flex justify-start">
                    <div className="bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] text-white max-w-[80%] rounded-xl px-4 py-3 shadow-sm">
                      <div className="flex gap-1.5 py-1">
                        <div className="w-2 h-2 bg-[rgba(255,255,255,0.6)] rounded-full animate-bounce" />
                        <div className="w-2 h-2 bg-[rgba(255,255,255,0.6)] rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                        <div className="w-2 h-2 bg-[rgba(255,255,255,0.6)] rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                      </div>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <div className="px-5 py-4 border-t border-[rgba(46,213,115,0.08)] bg-[rgba(0,0,0,0.6)] z-10">
                <div className="flex gap-3 items-center">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Ask anything e.g. show last 5 anomalies..."
                    className="flex-1 p-3 rounded-xl bg-[rgba(0,0,0,0.5)] border border-[rgba(46,213,115,0.18)] text-white focus:outline-none focus:border-[rgba(46,213,115,0.55)] focus:shadow-[0_0_0_3px_rgba(46,213,115,0.07)] transition-all font-['Inter',system-ui] text-[14px] placeholder-[rgba(255,255,255,0.2)]"
                    disabled={isTyping}
                  />
                  <div className="btn-wrapper" style={{ height: '46px', minWidth: '90px' }}>
                    <button onClick={handleSend} disabled={!input.trim() || isTyping} className="custom-btn">
                      <span className="btn-txt" style={{ fontSize: '13px' }}>Send</span>
                    </button>
                    <div className="dot"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toggle Button */}
      {!isOpen && (
        <div className="fixed bottom-6 left-6 z-40">
          <button
            onClick={() => setIsOpen(true)}
            className="relative bg-[rgba(0,0,0,0.8)] border border-[rgba(46,213,115,0.3)] hover:border-[rgba(46,213,115,0.8)] text-[rgb(46,213,115)] w-14 h-14 rounded-full shadow-[0_0_15px_rgba(46,213,115,0.2)] hover:shadow-[0_0_25px_rgba(46,213,115,0.4)] transition-all hover:scale-110 flex items-center justify-center backdrop-blur-sm"
          >
            <div className="toggle-point trigger" style={{ top: '4px', right: '4px', bottom: 'auto', left: 'auto' }}></div>
            <MessageCircle className="w-6 h-6" />
          </button>
        </div>
      )}
    </>
  );
}