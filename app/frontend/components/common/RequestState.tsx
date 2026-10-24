import { RotateCcw, TriangleAlert } from "lucide-react";
export function RequestState({
  error = false,
  retry,
}: {
  error?: boolean;
  retry?: () => void;
}) {
  return (
    <div className="empty-state" role={error ? "alert" : "status"}>
      {error ? (
        <>
          <TriangleAlert size={23} />
          <h2>Data belum dapat ditampilkan</h2>
          <p>Snapshot tidak berhasil diambil. Silakan coba lagi.</p>
          {retry && (
            <button className="ui-button mt-4" onClick={retry}>
              <RotateCcw size={14} />
              Coba lagi
            </button>
          )}
        </>
      ) : (
        <>
          <div className="skeleton mx-auto mb-4 h-4 w-32" />
          <p>Memuat snapshot…</p>
        </>
      )}
    </div>
  );
}
