/** A narrative frame, a video play symbol, and a light completing the frame. */
export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M33 18H20a5 5 0 0 0-5 5v17a5 5 0 0 0 5 5h3v7l10-7h10a5 5 0 0 0 5-5v-8"
        stroke="currentColor"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="m27 26 12 7-12 7Z"
        fill="currentColor"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M46 9c0 6-4 10-10 10 6 0 10 4 10 10 0-6 4-10 10-10-6 0-10-4-10-10Z"
        fill="currentColor"
      />
    </svg>
  );
}
