"use client";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
/** Planned pricing is informational; billing and quotas are not enforced yet. */
export function Plans() {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h3 className="text-sm font-medium">Free during pre-alpha</h3>
        <p className="text-xs text-muted-foreground">
          Use your own OpenRouter key. Model charges go to your provider.
        </p>
      </div>
      <section className="space-y-2 border-t pt-4">
        <h3 className="text-sm font-medium">Planned subscriptions</h3>
        <p className="text-xs text-muted-foreground">
          Pricing preview only. Billing and these plan limits are not active.
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Plan</TableHead>
              <TableHead>Price</TableHead>
              <TableHead className="text-right">Answers / month</TableHead>
              <TableHead className="text-right">Dataset allowance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>Free</TableCell>
              <TableCell>$0</TableCell>
              <TableCell className="text-right">50,000</TableCell>
              <TableCell className="text-right">2 GB</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Pro</TableCell>
              <TableCell>$20 / month</TableCell>
              <TableCell className="text-right">2 million</TableCell>
              <TableCell className="text-right">25 GB</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Team</TableCell>
              <TableCell>$20 / seat / month</TableCell>
              <TableCell className="text-right">5 million / seat</TableCell>
              <TableCell className="text-right">100 GB</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Badge variant="secondary">Paid plans coming later</Badge>
      </section>
    </div>
  );
}
