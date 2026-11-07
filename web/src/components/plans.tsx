"use client";

import { Badge } from "@/components/ui/badge";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";

// What the plans will be. Until billing exists, everyone is on Free with their own model key.
const PLANS = [
  {
    name: "Free",
    price: "$0",
    details: "Your own model key · 50,000 answers a month · 2 GB of datasets",
    current: true,
  },
  {
    name: "Pro",
    price: "$20 a month",
    details: "Your own key or credits · 2 million answers a month · 25 GB",
    current: false,
  },
  {
    name: "Team",
    price: "$20 a seat a month",
    details: "Your own key or credits · 5 million answers a month per seat · 100 GB",
    current: false,
  },
];

/** The plans there will be: a teaser until billing is built. */
export function Plans() {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Everyone is on Free for now, with their own OpenRouter key (Settings → Providers). Paid
        plans, and credits instead of a key of your own, are coming.
      </p>
      <ItemGroup className="gap-1">
        {PLANS.map((plan) => (
          <Item key={plan.name} variant="outline" size="sm">
            <ItemContent>
              <ItemTitle>
                {plan.name} <span className="font-normal text-muted-foreground">{plan.price}</span>
              </ItemTitle>
              <ItemDescription>{plan.details}</ItemDescription>
            </ItemContent>
            <ItemActions>
              {plan.current ? (
                <Badge>Your plan</Badge>
              ) : (
                <Badge variant="secondary">Coming soon</Badge>
              )}
            </ItemActions>
          </Item>
        ))}
      </ItemGroup>
    </div>
  );
}
