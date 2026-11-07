"use client";

import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import { Spinner } from "@/components/ui/spinner";
import { api, type Me, type Role } from "@/lib/api/client";

const MeContext = createContext<Me | null>(null);

/** Who is signed in, loaded once for everything inside. Signed out, the API client goes to sign-in. */
export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me>();
  useEffect(() => {
    api.GET("/v1/me").then(({ data }) => setMe(data));
  }, []);
  if (!me) return <Spinner className="m-6" />;
  return <MeContext value={me}>{children}</MeContext>;
}

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe needs a MeProvider");
  return me;
}

const ROLES: Role[] = ["verifier", "member", "admin"];

/** Whether the signed-in person's role is `role` or above. Locally, always. */
export function useCan(role: Role): boolean {
  const me = useMe();
  return ROLES.indexOf(me.role) >= ROLES.indexOf(role);
}
