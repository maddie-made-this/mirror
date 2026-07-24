export default function Footer() {
  return (
    <footer className="w-full border-t border-[var(--header-border)] bg-[var(--header-bg)] shrink-0 mt-auto transition-colors duration-500">
      <div className="max-w-4xl mx-auto p-6 flex flex-col items-center gap-2 text-xs sm:text-sm text-[var(--header-fg)] transition-colors duration-500">
        <div className="text-xs opacity-60">
          Made by Madison Dalton ·{" "}
          <a
            href="https://github.com/maddie-made-this"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:opacity-100 opacity-80 transition-opacity duration-300"
          >
            GitHub
          </a>
        </div>
      </div>
    </footer>
  );
}
