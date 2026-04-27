import { useState, useRef, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { MessageCircle, X, Send } from "lucide-react";

interface Message {
  id: string;
  text: string;
  sender: "user" | "bot";
  timestamp: Date;
}

export default function Chatbot() {
  const location = useLocation();

  // ⛔ Hide chatbot on login page
  if (location.pathname === "/login") {
    return null;
  }

  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      text: "Hey! 👋 How can I help you with the surveillance system today?",
      sender: "bot",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const getBotResponse = (userMessage: string): string => {
    const msg = userMessage.toLowerCase();

    if (msg.includes("hello") || msg.includes("hi") || msg.includes("hey")) {
      return "Hey there! 😊 How can I assist you with the surveillance system today?";
    }
    if (msg.includes("how are you")) {
      return "I'm running smoothly! How can I help with the monitoring tasks?";
    }
    if (msg.includes("help")) {
      return "I'm here to help! Ask me anything about the surveillance system or its features.";
    }
    if (msg.includes("campus")) {
      return "Regarding the surveillance system, I can provide info on cameras, alerts, and monitoring setup.";
    }
    if (msg.includes("course") || msg.includes("class")) {
      return "I can guide you through the system usage or features, instead of courses.";
    }
    if (msg.includes("bye") || msg.includes("goodbye")) {
      return "Goodbye! Feel free to chat anytime about the surveillance system. 👋";
    }

    return "That's interesting! Tell me more, or ask me something about the surveillance system. I'm here to help! 💬";
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      text: input,
      sender: "user",
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsTyping(true);

    setTimeout(() => {
      const botResponse: Message = {
        id: (Date.now() + 1).toString(),
        text: getBotResponse(input),
        sender: "bot",
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, botResponse]);
      setIsTyping(false);
    }, 1000);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Modal & Backdrop */}
      {isOpen && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => setIsOpen(false)}
        >
          <div 
            className="w-full max-w-2xl h-[80vh] bg-white dark:bg-zinc-800 shadow-2xl rounded-2xl overflow-hidden flex flex-col border border-gray-200 dark:border-zinc-700 animate-in fade-in zoom-in duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="px-6 py-4 border-b dark:border-zinc-700 bg-white dark:bg-zinc-800 flex justify-between items-center">
              <h2 className="text-xl font-semibold text-zinc-800 dark:text-white">
                Chatbot Assistant
              </h2>
              <button
                onClick={() => setIsOpen(false)}
                className="text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-white transition-colors p-1"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 p-6 overflow-y-auto flex flex-col space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"
                    }`}
                >
                  <div
                    className={`chat-message max-w-[80%] rounded-xl px-4 py-3 text-[15px] shadow-sm ${message.sender === "user"
                        ? "self-end bg-emerald-600 text-white"
                        : "self-start bg-zinc-500 text-white"
                      }`}
                  >
                    <p>{message.text}</p>
                    <p
                      className={`text-[11px] mt-1.5 text-right ${message.sender === "user"
                          ? "text-emerald-100"
                          : "text-zinc-200"
                        }`}
                    >
                      {message.timestamp.toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>
                </div>
              ))}

              {isTyping && (
                <div className="flex justify-start">
                  <div className="self-start bg-zinc-500 text-white max-w-[80%] rounded-xl px-4 py-3 shadow-sm">
                    <div className="flex gap-1.5 py-1">
                      <div className="w-2 h-2 bg-zinc-200 rounded-full animate-bounce" />
                      <div
                        className="w-2 h-2 bg-zinc-200 rounded-full animate-bounce"
                        style={{ animationDelay: "150ms" }}
                      />
                      <div
                        className="w-2 h-2 bg-zinc-200 rounded-full animate-bounce"
                        style={{ animationDelay: "300ms" }}
                      />
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="px-5 py-4 border-t dark:border-zinc-700 bg-white dark:bg-zinc-800">
              <div className="flex gap-3">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Type your message..."
                  className="flex-1 p-3 border rounded-xl dark:bg-zinc-700 text-black dark:text-black dark:border-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-[15px]"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim()}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2 px-6 rounded-xl transition duration-300 ease-in-out disabled:opacity-50 flex items-center justify-center text-[15px]"
                >
                  Send
                </button>
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
            className="bg-emerald-600 hover:bg-emerald-700 text-white w-14 h-14 rounded-full shadow-lg hover:shadow-xl transition-all hover:scale-110 flex items-center justify-center"
          >
            <MessageCircle className="w-6 h-6" />
          </button>
        </div>
      )}
    </>
  );
}
