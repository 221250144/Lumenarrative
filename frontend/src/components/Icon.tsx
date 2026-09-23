const paths: Record<string, string> = {
  user: "M20 21v-2a7 7 0 0 0-14 0v2M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8",
  sun: "M4 17a8 8 0 0 1 16 0M3 21h18M12 2v3M3 7l2 2M21 7l-2 2",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  film: "M4 3h16v18H4zM4 8h16M4 16h16M8 3v18M16 3v18",
  spark: "m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7z",
  check: "m5 12 4 4L19 6",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  upload: "M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5",
  play: "m8 4 13 8-13 8z",
  back: "M19 12H5m5-5-5 5 5 5",
  clock: "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  layers: "m12 3 10 5-10 5L2 8zm-10 9 10 5 10-5M2 16l10 5 10-5",
  close: "m6 6 12 12M6 18 18 6",
  copy: "M9 9h12v12H9zM15 9V3H3v12h6",
  refresh: "M20 7v5h-5M4 17v-5h5M19 11a7 7 0 0 0-12-6M5 13a7 7 0 0 0 12 6",
  alert: "m12 3 10 18H2zM12 9v5M12 17h.01",
  folder: "M3 5h7l2 3h9v13H3z",
  download: "M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2",
  volume: "M3 9h4l5-4v14l-5-4H3zM16 8a6 6 0 0 1 0 8",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
};
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.spark} />
    </svg>
  );
}
