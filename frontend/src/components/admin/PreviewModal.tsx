import React, { useEffect } from "react"

interface PreviewModalProps {
  open: boolean
  src: string | null
  title: string
  onClose: () => void
}

export function PreviewModal({ open, src, title, onClose }: PreviewModalProps) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        onClose()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onClose])

  if (!open || !src) return null

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/80 flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="relative max-w-3xl max-h-[90vh] w-full bg-zinc-950 border border-zinc-800 rounded-2xl p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <div className="text-white font-semibold">{title}</div>
          <button
            type="button"
            className="text-zinc-300 hover:text-white text-sm px-3 py-1 rounded-md border border-zinc-700"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <div className="flex items-center justify-center overflow-auto max-h-[75vh] rounded-lg bg-black">
          <img
            src={src}
            alt={title}
            className="max-w-full max-h-[75vh] object-contain"
          />
        </div>
      </div>
    </div>
  )
}
