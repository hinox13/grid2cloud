import { Suspense, lazy, useEffect } from "react";
import { useHashRoute } from "./components/hooks";
import { Loading } from "./data/load";
import { Experience } from "./scenes/Experience";
import { Home } from "./scenes/Home";

// The Explorer is a separate chunk: the first visit downloads only the home page and the story.
const Explorer = lazy(() => import("./explorer/Explorer"));

export function App() {
  const { path, params } = useHashRoute();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [path]);
  if (path.startsWith("/experience")) {
    const ch = path.split("/")[2] ?? null;
    return <Experience key={path + params.toString()} chapter={ch} />;
  }
  if (path.startsWith("/explore")) {
    return (
      <Suspense fallback={<Loading label="Loading the Explorer" />}>
        <Explorer path={path} params={params} />
      </Suspense>
    );
  }
  return <Home />;
}
