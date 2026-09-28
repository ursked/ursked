'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { OrgTreeNode } from '@/types';

// The organization unit an employee belongs to (users.org_node_id). This
// replaced a free-text "Division / Department" box whose value was never
// saved; units come from the Organization page, so there is one list.

export function useOrgUnits() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['org-tree'],
    queryFn: () => api.getOrgTree(),
    staleTime: 60_000,
  });
  const flat = useMemo(() => {
    const out: { id: number; name: string; depth: number; is_active: boolean }[] = [];
    const walk = (nodes: OrgTreeNode[], depth: number) => {
      for (const n of nodes) {
        out.push({ id: n.id, name: n.name, depth, is_active: n.is_active });
        walk(n.children || [], depth + 1);
      }
    };
    walk(data?.nodes ?? [], 0);
    return out;
  }, [data]);
  return { units: flat, isLoading, isError };
}

interface Props {
  id?: string;
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
  emptyLabel?: string;
  className?: string;
}

export default function OrgUnitSelect({ id, value, onChange, disabled, emptyLabel = 'No unit', className }: Props) {
  const { units, isLoading, isError } = useOrgUnits();
  return (
    <select
      id={id}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      disabled={disabled || isLoading}
      className={
        className ||
        'w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white disabled:bg-gray-50'
      }
    >
      <option value="">{isLoading ? 'Loading units…' : isError ? 'Could not load units' : emptyLabel}</option>
      {units
        .filter((u) => u.is_active || u.id === value)
        .map((u) => (
          <option key={u.id} value={u.id}>
            {'  '.repeat(u.depth)}
            {u.name}
          </option>
        ))}
    </select>
  );
}
