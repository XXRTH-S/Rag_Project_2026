import type { CSSProperties } from "react";
const paths: Record<string, string> = {
  book: "M4 5c3-2 5-2 8 0 3-2 5-2 8 0v15c-3-2-5-2-8 0-3-2-5-2-8 0V5Zm8 0v15",
  documents:
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Zm0 0v6h6M8 12h8M8 16h5",
  chat: "M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 0 1-1-5 9 9 0 0 1 18 0ZM8 10h8M8 14h5",
  playground: "M9 3h6M10 3v6L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M7 15h10",
  analytics: "M4 3v17h17M8 15v-4M13 15V7M18 15V4",
  users:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM17 4a4 4 0 0 1 0 7M22 21v-2a4 4 0 0 0-3-4",
  status: "M3 12h4l3-8 4 16 3-8h4",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  upload: "M12 16V3m-5 5 5-5 5 5M4 16v4h16v-4",
  search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "m6 6 12 12M6 18 18 6",
  logout: "M9 4H4v16h5M10 12h11m-4-4 4 4-4 4",
  plus: "M12 5v14M5 12h14",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  send: "m22 2-7 20-4-9-9-4L22 2ZM11 13 22 2",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  check: "m5 12 4 4L19 6",
  history: "M3 4v6h6M3 10a9 9 0 1 1 1 8M12 7v5l3 2",
  shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4Zm-4 10 3 3 5-6",
  leaf: "M20 3C8 1 2 7 5 15s15 5 15-12ZM4 21 16 8",
  copy: "M9 9h12v12H9V9ZM5 15H3V3h12v2",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z",
};
export function Icon({
  name,
  size = 20,
  style,
}: {
  name: string;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={style}
    >
      <path d={paths[name] || paths.book} />
    </svg>
  );
}
