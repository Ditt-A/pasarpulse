import { RotateCcw, TriangleAlert } from "lucide-react";
export function RequestState({
  error = false,
  retry,
}: {
  error?: boolean;
  retry?: () => void;
}) {
  return (
    <div className="surface empty-state" role={error ? "alert" : "status"}>
      {error ? (
        <>
          <TriangleAlert size={25} />
          <h2>Unable to load this workspace</h2>
          <p>The selected snapshot could not be retrieved. Please try again.</p>
          {retry && (
            <button className="ui-button mt-4" onClick={retry}>
              <RotateCcw size={13} />
              Try again
            </button>
          )}
        </>
      ) : (
        <>
          <div className="skeleton mx-auto mb-4 h-5 w-36" />
          <p>Loading the selected snapshot…</p>
        </>
      )}
    </div>
  );
}
