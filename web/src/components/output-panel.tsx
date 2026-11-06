import { FileOutputIcon } from "lucide-react";

import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";

/** The right column: the selected dataset's run details and export. Filled in by milestones 4 to 7. */
export function OutputPanel() {
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-semibold">Output</h2>
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileOutputIcon />
          </EmptyMedia>
          <EmptyTitle>No results yet</EmptyTitle>
          <EmptyDescription>
            Run progress, costs and exporting the selected dataset will appear here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}
