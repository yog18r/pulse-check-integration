/**
 * `useNow`: a React hook that returns the current time and re-renders the
 * component every `intervalMs`, so "2h ago" labels stay honest even when
 * Home Assistant has nothing new to tell us.
 *
 * React note: a hook is just a function whose name starts with `use` and
 * that calls other hooks. Here:
 *  - `useState` holds a value that survives re-renders and triggers one
 *    when it changes.
 *  - `useEffect` runs code after render (here: start a timer) and the
 *    function it returns runs on cleanup (stop the timer). The `[intervalMs]`
 *    dependency array means "re-run this effect only if intervalMs changes".
 */
import { useEffect, useState } from 'react';

export function useNow(intervalMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => {
      setNow(new Date());
    }, intervalMs);
    return () => {
      clearInterval(id);
    };
  }, [intervalMs]);

  return now;
}
