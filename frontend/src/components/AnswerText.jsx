// Renders the small Markdown subset Claude uses in answers (paragraphs, headings, lists,
// **bold**, *italic*, `code`) as React elements. Never uses dangerouslySetInnerHTML, so any
// HTML in the answer is shown as text.

const INLINE_RE = /(\*\*[^*]+?\*\*|\*[^*\s][^*]*?\*|`[^`]+`)/g;
const UNORDERED_RE = /^\s*[-*+]\s+(.*)$/;
const ORDERED_RE = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING_RE = /^\s*#{1,6}\s+(.*)$/;

function renderInline(text) {
  // split() with a capture group puts the matched Markdown spans at odd indexes.
  return text.split(INLINE_RE).map((part, index) => {
    if (index % 2 === 0) {
      return part;
    }
    if (part.startsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-gray-800">
          {renderInline(part.slice(2, -2))}
        </strong>
      );
    }
    if (part.startsWith("`")) {
      return (
        <code key={index} className="rounded bg-[#F5F5F4] px-1 font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <em key={index}>{part.slice(1, -1)}</em>;
  });
}

function parseBlocks(text) {
  const blocks = [];
  let current = null;

  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    const unordered = line.match(UNORDERED_RE);
    const ordered = !unordered && line.match(ORDERED_RE);
    const heading = !unordered && !ordered && line.match(HEADING_RE);

    if (!line.trim()) {
      current = null;
    } else if (unordered || ordered) {
      const type = unordered ? "ul" : "ol";
      if (current?.type !== type) {
        current = { type, start: ordered ? Number(ordered[1]) : 1, items: [] };
        blocks.push(current);
      }
      current.items.push(unordered ? unordered[1] : ordered[2]);
    } else if (heading) {
      blocks.push({ type: "heading", text: heading[1] });
      current = null;
    } else if (current?.type === "ul" || current?.type === "ol") {
      current.items[current.items.length - 1] += ` ${line.trim()}`;
    } else if (current?.type === "p") {
      current.lines.push(line.trim());
    } else {
      current = { type: "p", lines: [line.trim()] };
      blocks.push(current);
    }
  }

  return blocks;
}

export default function AnswerText({ text, className = "" }) {
  return (
    <div className={`space-y-3 ${className}`}>
      {parseBlocks(text).map((block, index) => {
        if (block.type === "heading") {
          return (
            <p key={index} className="font-semibold text-gray-800">
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.type === "ul" || block.type === "ol") {
          const List = block.type;
          return (
            <List
              key={index}
              start={block.type === "ol" ? block.start : undefined}
              className={`space-y-1 pl-5 ${block.type === "ul" ? "list-disc" : "list-decimal"}`}
            >
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </List>
          );
        }
        return <p key={index}>{renderInline(block.lines.join(" "))}</p>;
      })}
    </div>
  );
}
