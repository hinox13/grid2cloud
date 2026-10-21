export function Wordmark({ label }: { label?: string }) {
  return (
    <a className="wordmark" href="#/" aria-label={label ?? "Cloud2Grid home"}>
      Cloud2Grid
    </a>
  );
}
