'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import { hasRole } from '@/lib/roles';
import {
  Badge, Button, Checkbox, ConfirmDialog, EmptyState, FormField, Input, Modal, Select, Switch,
  Tabs, TabsContent, TabsList, TabsTrigger, Textarea,
} from '@/components/ui';
import { useToast } from '@/components/ui/Toast';
import type { Entitlement, LicenceInfo, PluginDelivery, PluginInfo, PluginList } from '@/types';

// Admin › Plugins (ops/PLUGINS_AND_LICENSING.md 2.6). Every plugin ships in the
// image and is locked until the licence includes it. Backed by /plugins and
// /licence, which answer only in an administrator session.

type Tone = 'gray' | 'purple' | 'green' | 'yellow' | 'red' | 'blue';

function fmtDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function entitlementLabel(e: Entitlement | null): { text: string; tone: Tone } {
  if (!e || e.state === 'none') return { text: 'Not licensed', tone: 'gray' };
  switch (e.state) {
    case 'active': return { text: `Licensed until ${fmtDate(e.expires)}`, tone: 'green' };
    case 'trial': return { text: `Trial until ${fmtDate(e.expires)}`, tone: 'blue' };
    case 'grace': return { text: `Expired, still running until ${fmtDate(e.grace_until)}`, tone: 'yellow' };
    case 'over_limit': return { text: `Over its employee limit (${e.used} of ${e.seats})`, tone: 'yellow' };
    case 'paused_over_limit': return { text: `Paused: over its employee limit (${e.used} of ${e.seats})`, tone: 'red' };
    case 'expired': return { text: `Expired ${fmtDate(e.expires)}`, tone: 'red' };
    default: return { text: e.state, tone: 'gray' };
  }
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : 'Something went wrong.';
}

function BuyHint({ storeUrl, installId, pluginId }: { storeUrl: string; installId: string; pluginId?: string }) {
  if (storeUrl) {
    const url = new URL(storeUrl);
    url.searchParams.set('install', installId);
    if (pluginId) url.searchParams.set('plugin', pluginId);
    return (
      <a href={url.toString()} target="_blank" rel="noopener noreferrer"
        className="text-sm font-medium text-brand-600 hover:text-brand-700">
        Buy or start a trial
      </a>
    );
  }
  return (
    <p className="text-sm text-gray-500">
      To buy or try it, send your ursked provider this install&apos;s ID (under Licence).
    </p>
  );
}

// ── settings ────────────────────────────────────────────────────────────────

function SettingsModal({ plugin, open, onOpenChange }: {
  plugin: PluginInfo; open: boolean; onOpenChange: (o: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  // Mounted only while open (PluginCard), so every opening starts from the
  // saved values.
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const v: Record<string, unknown> = {};
    for (const f of plugin.fields) if (f.type !== 'secret') v[f.key] = plugin.values[f.key] ?? f.default;
    return v;
  });
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [cleared, setCleared] = useState<Record<string, boolean>>({});

  const save = useMutation({
    mutationFn: () => {
      const out: Record<string, unknown> = { ...values };
      for (const f of plugin.fields) {
        if (f.type !== 'secret') continue;
        if (secrets[f.key]) out[f.key] = secrets[f.key];
        else if (cleared[f.key]) out[f.key] = '';
      }
      return api.savePluginSettings(plugin.id, out);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
      showToast(`${plugin.name} settings saved.`, 'success');
      onOpenChange(false);
    },
    onError: (err) => showToast(errorText(err), 'error'),
  });

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`${plugin.name} settings`}
      size="lg"
      footer={(
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
        </>
      )}
    >
      <div className="space-y-5">
        {plugin.fields.map((f) => {
          const id = `pf-${plugin.id}-${f.key}`;
          if (f.type === 'bool') {
            return (
              <div key={f.key} className="flex items-start justify-between gap-4">
                <div>
                  <label htmlFor={id} className="text-sm font-medium text-gray-700">{f.label}</label>
                  {f.help && <p className="mt-0.5 text-xs text-gray-500">{f.help}</p>}
                </div>
                <Switch id={id} checked={Boolean(values[f.key])} onChange={(c) => setValues({ ...values, [f.key]: c })} />
              </div>
            );
          }
          if (f.type === 'secret') {
            const isSet = Boolean((plugin.values[f.key] as { set?: boolean } | undefined)?.set) && !cleared[f.key];
            return (
              <FormField key={f.key} label={f.label} htmlFor={id} help={f.help ?? undefined} required={f.required}>
                <div className="flex gap-2">
                  <Input
                    id={id}
                    type="password"
                    autoComplete="off"
                    value={secrets[f.key] ?? ''}
                    placeholder={isSet ? 'Set. Type a new value to replace it.' : 'Not set'}
                    onChange={(e) => setSecrets({ ...secrets, [f.key]: e.target.value })}
                  />
                  {isSet && !f.required && (
                    <Button variant="ghost" type="button" onClick={() => setCleared({ ...cleared, [f.key]: true })}>
                      Clear
                    </Button>
                  )}
                </div>
              </FormField>
            );
          }
          if (f.type === 'multiselect') {
            const chosen = new Set((values[f.key] as string[] | undefined) ?? []);
            return (
              <FormField key={f.key} label={f.label} help={f.help ?? undefined}>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                  {f.options.map((o) => (
                    <label key={o.value} className="flex items-center gap-2 text-sm text-gray-700">
                      <Checkbox
                        checked={chosen.has(o.value)}
                        onChange={(e) => {
                          const next = new Set(chosen);
                          if (e.target.checked) next.add(o.value); else next.delete(o.value);
                          setValues({ ...values, [f.key]: Array.from(next) });
                        }}
                      />
                      {o.label}
                    </label>
                  ))}
                </div>
              </FormField>
            );
          }
          if (f.type === 'select') {
            return (
              <FormField key={f.key} label={f.label} htmlFor={id} help={f.help ?? undefined} required={f.required}>
                <Select id={id} value={String(values[f.key] ?? '')}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                  {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Select>
              </FormField>
            );
          }
          return (
            <FormField key={f.key} label={f.label} htmlFor={id} help={f.help ?? undefined} required={f.required}>
              <Input
                id={id}
                type={f.type === 'number' ? 'number' : f.type === 'url' ? 'url' : 'text'}
                value={String(values[f.key] ?? '')}
                onChange={(e) => setValues({
                  ...values,
                  [f.key]: f.type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value,
                })}
              />
            </FormField>
          );
        })}
        {plugin.scopes.length > 0 && (
          <p className="text-xs text-gray-500">
            This plugin receives: {plugin.scopes.map((s) => s.label.toLowerCase()).join(', ')}. Never pay or salary details.
          </p>
        )}
      </div>
    </Modal>
  );
}

// ── activity ───────────────────────────────────────────────────────────────

const STATUS_TONE: Record<PluginDelivery['status'], Tone> = {
  queued: 'blue', sent: 'green', failed: 'red', skipped: 'gray',
};
const STATUS_TEXT: Record<PluginDelivery['status'], string> = {
  queued: 'Waiting', sent: 'Sent', failed: 'Failed', skipped: 'Not sent',
};

function ActivityModal({ plugin, open, onOpenChange }: {
  plugin: PluginInfo; open: boolean; onOpenChange: (o: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { data = [], isLoading } = useQuery({
    queryKey: ['plugin-activity', plugin.id],
    queryFn: () => api.getPluginActivity(plugin.id),
    enabled: open,
  });
  const retry = useMutation({
    mutationFn: (rowId: number) => api.retryPluginDelivery(plugin.id, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugin-activity', plugin.id] });
      showToast('It will be sent again within a minute.', 'success');
    },
    onError: (err) => showToast(errorText(err), 'error'),
  });

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`${plugin.name} activity`} size="xl"
      description="What this plugin was sent in the last 30 days. Failed deliveries are retried for about a day before they stop.">
      {isLoading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : data.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing yet. Events appear here once the plugin is on and something happens.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="py-2 pr-4 font-medium">When</th>
                <th className="py-2 pr-4 font-medium">Event</th>
                <th className="py-2 pr-4 font-medium">Result</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="py-2 pr-4 whitespace-nowrap text-gray-600">{fmtWhen(d.created_at)}</td>
                  <td className="py-2 pr-4 text-gray-900">{d.label}</td>
                  <td className="py-2 pr-4">
                    <Badge tone={STATUS_TONE[d.status]}>{STATUS_TEXT[d.status]}</Badge>
                    {d.attempts > 1 && <span className="ml-2 text-xs text-gray-500">{d.attempts} attempts</span>}
                    {d.last_error && <p className="mt-1 text-xs text-gray-600 break-words">{d.last_error}</p>}
                    {d.next_attempt_at && d.attempts > 0 && (
                      <p className="mt-1 text-xs text-gray-500">Next try {fmtWhen(d.next_attempt_at)}</p>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {(d.status === 'failed' || d.status === 'skipped') && (
                      <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === d.id}
                        onClick={() => retry.mutate(d.id)}>
                        Send again
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

// ── one plugin ─────────────────────────────────────────────────────────────

function PluginCard({ plugin, list }: { plugin: PluginInfo; list: PluginList }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const state = entitlementLabel(plugin.entitlement);
  const licensed = plugin.tier === 'free' || Boolean(plugin.entitlement?.runs);

  const toggle = useMutation({
    mutationFn: (on: boolean) => api.setPluginEnabled(plugin.id, on),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
      showToast(`${p.name} is ${p.enabled ? 'on' : 'off'}.`, 'success');
    },
    onError: (err) => showToast(errorText(err), 'error'),
  });
  const test = useMutation({
    mutationFn: () => api.testPlugin(plugin.id),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
      showToast(r.message, r.ok ? 'success' : 'error');
    },
    onError: (err) => showToast(errorText(err), 'error'),
  });

  const failed = plugin.activity.failed ?? 0;
  const waiting = plugin.activity.queued ?? 0;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-gray-900">{plugin.name}</h2>
            <span className="text-xs text-gray-400">v{plugin.version}</span>
            {plugin.tier === 'paid' && <Badge tone={state.tone}>{state.text}</Badge>}
            {plugin.enabled && plugin.runs && <Badge tone="purple">On</Badge>}
            {plugin.enabled && !plugin.runs && <Badge tone="red">On, but paused</Badge>}
          </div>
          <p className="mt-1 text-sm text-gray-600">{plugin.summary}</p>
          {plugin.description && <p className="mt-2 text-sm text-gray-500">{plugin.description}</p>}
          {!plugin.loaded && (
            <p className="mt-2 text-sm text-red-700">This plugin could not be loaded: {plugin.error}</p>
          )}
          {plugin.enabled && plugin.missing.length > 0 && (
            <p className="mt-2 text-sm text-amber-700">Missing: {plugin.missing.join(', ')}.</p>
          )}
          {plugin.last_test && (
            <p className={`mt-2 text-xs ${plugin.last_test.ok ? 'text-gray-500' : 'text-red-700'}`}>
              Last test {fmtWhen(plugin.last_test.at)}: {plugin.last_test.message}
            </p>
          )}
          {(failed > 0 || waiting > 0) && (
            <p className="mt-2 text-xs text-gray-600">
              {waiting > 0 && <>{waiting} waiting to send. </>}
              {failed > 0 && <span className="text-red-700">{failed} failed. </span>}
              <button type="button" className="text-brand-600 hover:text-brand-700 font-medium" onClick={() => setActivityOpen(true)}>
                See activity
              </button>
            </p>
          )}
          {!licensed && plugin.loaded && (
            <div className="mt-3"><BuyHint storeUrl={list.store_url} installId={list.install_id} pluginId={plugin.id} /></div>
          )}
        </div>
        <div className="flex sm:flex-col items-center sm:items-end gap-3 shrink-0">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <span>{plugin.enabled ? 'On' : 'Off'}</span>
            <Switch
              checked={plugin.enabled}
              disabled={toggle.isPending || (!plugin.enabled && (!licensed || !plugin.loaded))}
              onChange={(c) => toggle.mutate(c)}
            />
          </label>
          <div className="flex gap-2">
            {plugin.fields.length > 0 && (
              <Button size="sm" variant="secondary" disabled={!plugin.loaded} onClick={() => setSettingsOpen(true)}>Settings</Button>
            )}
            {plugin.has_test && (
              <Button size="sm" variant="secondary" disabled={!licensed} loading={test.isPending} onClick={() => test.mutate()}>Test</Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setActivityOpen(true)}>Activity</Button>
          </div>
        </div>
      </div>
      {settingsOpen && <SettingsModal plugin={plugin} open onOpenChange={setSettingsOpen} />}
      <ActivityModal plugin={plugin} open={activityOpen} onOpenChange={setActivityOpen} />
    </div>
  );
}

// ── licence ────────────────────────────────────────────────────────────────

function LicenceTab({ licence }: { licence: LicenceInfo }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [key, setKey] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['licence'] });
    queryClient.invalidateQueries({ queryKey: ['plugins'] });
  };
  const apply = useMutation({
    mutationFn: () => api.applyLicence(key),
    onSuccess: () => { refresh(); setKey(''); showToast('Licence key applied.', 'success'); },
    onError: (err) => showToast(errorText(err), 'error'),
  });
  const remove = useMutation({
    mutationFn: () => api.removeLicence(),
    onSuccess: () => { refresh(); setConfirmRemove(false); showToast('Licence key removed.', 'success'); },
    onError: (err) => showToast(errorText(err), 'error'),
  });

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(licence.install_id);
      showToast('Install ID copied.', 'success');
    } catch {
      showToast('Could not copy. Select the ID and copy it by hand.', 'error');
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h2 className="text-base font-semibold text-gray-900">This install</h2>
        <p className="mt-1 text-sm text-gray-500">
          A licence key only works on the install whose ID it was issued for. Give this ID when you buy or start a trial.
          Moving to a new server with a backup keeps it.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <code className="rounded-md bg-gray-50 border border-gray-200 px-3 py-1.5 text-sm text-gray-900 select-all break-all">
            {licence.install_id}
          </code>
          <Button size="sm" variant="secondary" onClick={copyId}>Copy</Button>
        </div>
        <div className="mt-3"><BuyHint storeUrl={licence.store_url} installId={licence.install_id} /></div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Licence</h2>
            {licence.licence ? (
              <p className="mt-1 text-sm text-gray-500">
                {licence.licence.lid}
                {licence.licence.customer?.name && <> for {licence.licence.customer.name}</>}, issued {fmtDate(licence.licence.issued)}.
                {' '}{licence.active_employees} active {licence.active_employees === 1 ? 'person counts' : 'people count'} towards employee limits.
              </p>
            ) : (
              <p className="mt-1 text-sm text-gray-500">No licence key is applied, so paid plugins are locked.</p>
            )}
          </div>
          {licence.applied && (
            <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>Remove key</Button>
          )}
        </div>
        {licence.error && (
          <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{licence.error}</p>
        )}
        {licence.entitlements.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500">
                  <th className="py-2 pr-4 font-medium">Plugin</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Expires</th>
                  <th className="py-2 font-medium">Employees</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {licence.entitlements.map((e) => {
                  const st = entitlementLabel(e);
                  return (
                    <tr key={e.plugin}>
                      <td className="py-2 pr-4 text-gray-900">
                        {e.name}
                        {!e.installed && <span className="ml-2 text-xs text-gray-500">(not in this version)</span>}
                      </td>
                      <td className="py-2 pr-4"><Badge tone={st.tone}>{e.trial ? 'Trial' : st.tone === 'green' ? 'Active' : st.text}</Badge></td>
                      <td className="py-2 pr-4 text-gray-600">{fmtDate(e.expires)}</td>
                      <td className={`py-2 ${e.near_limit ? 'text-amber-700 font-medium' : 'text-gray-600'}`}>
                        {e.seats != null ? `${e.used} of ${e.seats}` : 'No limit'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h2 className="text-base font-semibold text-gray-900">Apply a licence key</h2>
        <p className="mt-1 text-sm text-gray-500">
          Paste the whole key you were sent. It starts with URSKED1. A newer key replaces the one applied now.
        </p>
        <Textarea
          className="mt-3 font-mono text-xs"
          rows={4}
          value={key}
          placeholder="URSKED1.…"
          onChange={(e) => setKey(e.target.value)}
        />
        <div className="mt-3 flex justify-end">
          <Button onClick={() => apply.mutate()} loading={apply.isPending} disabled={key.trim().length < 10}>
            Apply key
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title="Remove the licence key?"
        description="Paid plugins stop running straight away. Their settings are kept, and applying a key again turns them back on."
        confirmLabel="Remove key"
        variant="danger"
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

// ── page ───────────────────────────────────────────────────────────────────

export default function PluginsPage() {
  const { user } = useAuth();
  const isAdmin = !!user && hasRole(user, 'tenant_admin');

  const plugins = useQuery({ queryKey: ['plugins'], queryFn: () => api.getPlugins(), enabled: isAdmin });
  const licence = useQuery({ queryKey: ['licence'], queryFn: () => api.getLicence(), enabled: isAdmin });

  if (user && !isAdmin) {
    return (
      <DashboardLayout>
        <div className="max-w-xl mx-auto py-16 text-center">
          <h1 className="text-xl font-semibold text-gray-900">Plugins</h1>
          <p className="mt-2 text-sm text-gray-600">Only administrators can manage plugins.</p>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Plugins</h1>
          <p className="mt-1 text-sm text-gray-500">
            Connect ursked to other tools. Plugins are unlocked by your licence key and turned on here.
          </p>
        </div>

        <Tabs defaultValue="plugins">
          <TabsList>
            <TabsTrigger value="plugins">Plugins</TabsTrigger>
            <TabsTrigger value="licence">Licence</TabsTrigger>
          </TabsList>

          <TabsContent value="plugins" className="pt-4">
            {plugins.isLoading ? (
              <p className="text-sm text-gray-500">Loading…</p>
            ) : plugins.isError ? (
              <p className="text-sm text-red-700">{errorText(plugins.error)}</p>
            ) : plugins.data && plugins.data.plugins.length > 0 ? (
              <div className="space-y-4">
                {plugins.data.plugins.map((p) => <PluginCard key={p.id} plugin={p} list={plugins.data} />)}
              </div>
            ) : (
              <EmptyState
                title="No plugins in this version"
                description="This build of ursked was made without plugins. The official images on Docker Hub include them."
              />
            )}
          </TabsContent>

          <TabsContent value="licence" className="pt-4">
            {licence.isLoading ? (
              <p className="text-sm text-gray-500">Loading…</p>
            ) : licence.isError ? (
              <p className="text-sm text-red-700">{errorText(licence.error)}</p>
            ) : licence.data ? (
              <LicenceTab licence={licence.data} />
            ) : null}
          </TabsContent>
        </Tabs>
      </div>
    </DashboardLayout>
  );
}
