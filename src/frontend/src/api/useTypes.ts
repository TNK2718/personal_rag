import useSWR, { mutate } from "swr";
import { useMemo } from "react";
import { fetcher } from "./client";
import type { EntityTypeDef, RelationTypeDef } from "./types";

const ENTITY_TYPES_KEY = "/api/types/entities";
const RELATION_TYPES_KEY = "/api/types/relations";

/**
 * Shared SWR cache over the runtime type registry.
 *
 * Components that render dynamic forms or schema-driven columns subscribe to
 * this hook so the prompt-to-paint path is single-fetch and the cache survives
 * navigations. After a Settings edit, call ``refresh()`` to broadcast a
 * revalidation to every subscriber.
 */
export function useTypes() {
  const entities = useSWR<EntityTypeDef[]>(ENTITY_TYPES_KEY, fetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  });
  const relations = useSWR<RelationTypeDef[]>(RELATION_TYPES_KEY, fetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  });

  const entityBySlug = useMemo(() => {
    const m = new Map<string, EntityTypeDef>();
    for (const t of entities.data ?? []) m.set(t.slug, t);
    return m;
  }, [entities.data]);

  const relationBySlug = useMemo(() => {
    const m = new Map<string, RelationTypeDef>();
    for (const t of relations.data ?? []) m.set(t.slug, t);
    return m;
  }, [relations.data]);

  return {
    entityTypes: entities.data,
    relationTypes: relations.data,
    entityBySlug,
    relationBySlug,
    isLoading: entities.isLoading || relations.isLoading,
    error: entities.error || relations.error,
    refresh: () => {
      mutate(ENTITY_TYPES_KEY);
      mutate(RELATION_TYPES_KEY);
    },
  };
}

export function refreshTypes() {
  mutate(ENTITY_TYPES_KEY);
  mutate(RELATION_TYPES_KEY);
}
