"use client";

import { mergeAttributes, Node, type JSONContent } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { Dropcursor, Placeholder, UndoRedo } from "@tiptap/extensions";
import { Plugin } from "@tiptap/pm/state";
import {
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  type Editor,
  type ReactNodeViewProps,
} from "@tiptap/react";
import { createContext, useContext } from "react";

import { Badge } from "@/components/ui/badge";

// Same syntax as the server's `PLACEHOLDER`.
const PLACEHOLDER = /\{\{\s*(.+?)\s*\}\}/;

/** Field paths the dataset has, or null while they are loading. Unknown fields are shown in red. */
export const KnownFields = createContext<Set<string> | null>(null);

/** A `{{path}}` placeholder, shown as a chip. Any `{{path}}` text in the editor becomes one. */
const FieldNode = Node.create({
  name: "field",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes() {
    return { path: { default: "" } };
  },
  parseHTML() {
    return [{ tag: "span[data-field]", getAttrs: (el) => ({ path: el.dataset.field }) }];
  },
  renderHTML({ node, HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-field": node.attrs.path })];
  },
  renderText({ node }) {
    return `{{${node.attrs.path}}}`;
  },
  addNodeView() {
    return ReactNodeViewRenderer(FieldChip);
  },
  addProseMirrorPlugins() {
    const type = this.type;
    // After every change, so typed, pasted and dropped placeholders are all handled the same way.
    return [
      new Plugin({
        appendTransaction(transactions, _, state) {
          if (!transactions.some((tr) => tr.docChanged)) return null;
          const found: { from: number; to: number; path: string }[] = [];
          state.doc.descendants((node, pos) => {
            for (const match of node.isText ? node.text!.matchAll(new RegExp(PLACEHOLDER, "g")) : []) {
              const from = pos + match.index;
              found.push({ from, to: from + match[0].length, path: match[1] });
            }
          });
          if (!found.length) return null;
          const tr = state.tr;
          for (const { from, to, path } of found.reverse()) {
            tr.replaceWith(from, to, type.create({ path }));
          }
          return tr;
        },
      }),
    ];
  },
});

function FieldChip({ node }: ReactNodeViewProps) {
  const known = useContext(KnownFields);
  const path = node.attrs.path as string;
  return (
    <NodeViewWrapper as="span">
      <Badge variant={known && !known.has(path) ? "destructive" : "secondary"} className="font-mono">
        {path}
      </Badge>
    </NodeViewWrapper>
  );
}

/** A template as editor content: one paragraph per line, placeholders as field chips. */
function toDoc(template: string): JSONContent {
  return {
    type: "doc",
    content: template.split("\n").map((line) => {
      // Splitting on a pattern with a group alternates text and field paths.
      const content: JSONContent[] = line
        .split(new RegExp(PLACEHOLDER.source, "g"))
        .map((part, i) =>
          i % 2 ? { type: "field", attrs: { path: part } } : { type: "text", text: part },
        )
        .filter((part) => part.type === "field" || part.text);
      return { type: "paragraph", content };
    }),
  };
}

export function usePromptEditor(template: string, onChange: (template: string) => void) {
  return useEditor({
    extensions: [
      Document,
      Paragraph,
      Text,
      FieldNode,
      UndoRedo,
      Dropcursor,
      Placeholder.configure({
        placeholder: "Is this review negative? …then drag in the columns it is about.",
      }),
    ],
    content: toDoc(template),
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class:
          "min-h-32 w-full rounded-lg border border-input px-3 py-2 text-sm leading-7 outline-none select-text focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
      },
    },
    onUpdate: ({ editor }) => onChange(editor.getText({ blockSeparator: "\n" })),
  });
}

export function PromptEditor({ editor }: { editor: Editor | null }) {
  return <EditorContent editor={editor} />;
}
