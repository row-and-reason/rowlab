import { Button } from "@/components/ui/button";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** A button whose name, and keyboard shortcut if it has one, shows on hover. */
export function TooltipButton({
  label,
  keys,
  side,
  ...props
}: React.ComponentProps<typeof Button> & {
  label: string;
  keys?: string[];
  side?: React.ComponentProps<typeof TooltipContent>["side"];
}) {
  return (
    <Tooltip>
      <TooltipTrigger render={<Button aria-label={label} {...props} />} />
      <TooltipContent side={side}>
        {label}
        {keys && <Keys keys={keys} />}
      </TooltipContent>
    </Tooltip>
  );
}

/** A shortcut such as ⌘ ↵, shown key by key. */
export function Keys({ keys }: { keys: string[] }) {
  return (
    <KbdGroup>
      {keys.map((key) => (
        <Kbd key={key}>{key}</Kbd>
      ))}
    </KbdGroup>
  );
}
