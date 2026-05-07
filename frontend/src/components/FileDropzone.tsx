import { useRef, useState } from "react";
import { FileText, ImageIcon, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = ".jpg,.jpeg,.png,.pdf";

function formatBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(2)} MB`;
}

export function FileDropzone({
  label,
  file,
  onChange,
  error,
}: {
  label: string;
  file: File | null;
  onChange: (file: File | null) => void;
  error?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleFiles = (files: FileList | null) => {
    setLocalError(null);
    const f = files?.[0];
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setLocalError(`File too large (${formatBytes(f.size)} > 5 MB)`);
      return;
    }
    if (!/\.(jpe?g|png|pdf)$/i.test(f.name)) {
      setLocalError("Only JPG, PNG, or PDF allowed");
      return;
    }
    onChange(f);
  };

  const isImage = file?.type.startsWith("image/");
  const previewUrl = isImage && file ? URL.createObjectURL(file) : null;

  if (file) {
    return (
      <div className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2.5">
        <div className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted">
          {previewUrl ? (
            <img src={previewUrl} alt="preview" className="size-full object-cover" />
          ) : file.type === "application/pdf" ? (
            <FileText className="size-5 text-muted-foreground" />
          ) : (
            <ImageIcon className="size-5 text-muted-foreground" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
          <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground"
          onClick={() => onChange(null)}
          aria-label="Remove file"
        >
          <X className="size-4" />
        </Button>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex w-full items-center gap-3 rounded-lg border border-dashed bg-background px-3 py-3 text-left transition-colors",
          dragOver ? "border-primary bg-accent/50" : "border-border hover:border-foreground/30 hover:bg-muted/40",
        )}
      >
        <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
          <UploadCloud className="size-5" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium text-foreground">{label}</p>
          <p className="text-xs text-muted-foreground">JPG, PNG, or PDF · up to 5 MB</p>
        </div>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      {(localError || error) && (
        <p className="mt-1 text-xs text-destructive">{localError ?? error}</p>
      )}
    </div>
  );
}
