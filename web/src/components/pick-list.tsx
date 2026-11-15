"use client";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

export type PickGroup = {
  label: string;
  items: { value: string; label: string; detail?: string }[];
};

/**
 * A searchable list of choices in groups, for a popover: every choice is listed at once, typing
 * narrows them to those containing the text, and the picked ones are checked. `onPick` gets the value chosen; the caller toggles
 * it, or picks just it.
 */
export function PickList({
  groups,
  picked,
  onPick,
  placeholder,
  empty,
}: {
  groups: PickGroup[];
  picked: string[];
  onPick: (value: string) => void;
  placeholder: string;
  empty: string;
}) {
  return (
    <Command className="rounded-none! bg-transparent p-0" filter={contains}>
      <CommandInput placeholder={placeholder} />
      <CommandList>
        <CommandEmpty>{empty}</CommandEmpty>
        {groups
          .filter((group) => group.items.length)
          .map((group) => (
            <CommandGroup key={group.label} heading={group.label || undefined}>
              {group.items.map((item) => (
                <CommandItem
                  key={item.value}
                  value={item.value}
                  keywords={[item.label]}
                  data-checked={picked.includes(item.value)}
                  onSelect={() => onPick(item.value)}
                >
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.detail && (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {item.detail}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
      </CommandList>
    </Command>
  );
}

/** Whether a choice's value or label contains what was typed, ignoring case. */
function contains(value: string, search: string, keywords: string[] = []): number {
  const text = search.toLowerCase();
  return [value, ...keywords].some((s) => s.toLowerCase().includes(text)) ? 1 : 0;
}
