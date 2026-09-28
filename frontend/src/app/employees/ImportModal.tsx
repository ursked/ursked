'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import { Modal, Button } from '@/components/ui';
import type { EmployeeImportResult } from '@/types';

// Upload -> preview (nothing written) -> confirm -> summary. The preview runs
// the real import and rolls it back, so what it says is what will happen.

type Step = 'upload' | 'preview' | 'done';

const ACTION_STYLES: Record<string, { label: string; cls: string }> = {
  create: { label: 'Add', cls: 'bg-green-50 text-green-800' },
  update: { label: 'Update', cls: 'bg-blue-50 text-blue-800' },
  unchanged: { label: 'No change', cls: 'bg-gray-100 text-gray-700' },
  error: { label: 'Error', cls: 'bg-red-50 text-red-800' },
};

interface Props {
  onClose: () => void;
  onImported: () => void;
}

export default function ImportModal({ onClose, onImported }: Props) {
  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<EmployeeImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [onlyProblems, setOnlyProblems] = useState(false);

  const downloadTemplate = async () => {
    setError('');
    try {
      const blob = await api.downloadImportTemplate();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'employee-import-template.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not download the template.');
    }
  };

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.importUsersCsv(file, dryRun);
      setResult(res);
      setStep(dryRun ? 'preview' : 'done');
      if (!dryRun) onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The import failed.');
    } finally {
      setBusy(false);
    }
  };

  const rows = (result?.rows ?? []).filter((r) => !onlyProblems || r.action === 'error');
  const willChange = result ? result.created + result.updated : 0;

  const footer =
    step === 'upload' ? (
      <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => run(true)} disabled={!file} loading={busy}>Preview</Button>
      </>
    ) : step === 'preview' ? (
      <>
        <Button variant="secondary" onClick={() => { setStep('upload'); setResult(null); }}>Choose another file</Button>
        <Button onClick={() => run(false)} disabled={willChange === 0} loading={busy}>
          Import {willChange} {willChange === 1 ? 'employee' : 'employees'}
        </Button>
      </>
    ) : (
      <Button onClick={onClose}>Done</Button>
    );

  return (
    <Modal
      open
      onOpenChange={(o) => { if (!o) onClose(); }}
      title="Import employees"
      description={
        step === 'upload'
          ? 'Add or update many employees from a CSV file.'
          : step === 'preview'
            ? 'Nothing has been saved yet. Check the rows below, then import.'
            : 'Import finished.'
      }
      size="xl"
      footer={footer}
    >
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {step === 'upload' && (
        <div className="space-y-4 text-sm text-gray-700">
          <ul className="list-disc space-y-1 pl-5">
            <li>One row per employee. A row updates the employee with the same email (or employee number when the email cell is empty); otherwise it adds a new one.</li>
            <li>Blank cells leave existing values unchanged.</li>
            <li>Rows without a password create the employee as invited and send them an activation email.</li>
            <li>Employee type, schedule format, organization unit and roles can be given by name or code; the line manager by email or employee number.</li>
            <li>Up to 2,000 rows and 2 MB per file. Save from Excel as &ldquo;CSV UTF-8&rdquo;.</li>
          </ul>
          <button type="button" onClick={downloadTemplate} className="text-purple-700 underline underline-offset-2 hover:text-purple-900">
            Download a template with your company&apos;s columns
          </button>
          <div>
            <label htmlFor="import-file" className="block text-sm font-medium text-gray-700 mb-1">CSV file</label>
            <input
              id="import-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-purple-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-purple-700 hover:file:bg-purple-100"
            />
          </div>
        </div>
      )}

      {result && step !== 'upload' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: step === 'done' ? 'Added' : 'Will add', value: result.created },
              { label: step === 'done' ? 'Updated' : 'Will update', value: result.updated },
              { label: 'No change', value: result.unchanged },
              { label: 'Errors', value: result.failed },
            ].map((s) => (
              <div key={s.label} className="rounded-lg border border-gray-200 px-3 py-2">
                <p className="text-xs text-gray-500">{s.label}</p>
                <p className="text-lg font-semibold text-gray-900">{s.value}</p>
              </div>
            ))}
          </div>
          {result.ignored_columns.length > 0 && (
            <p className="text-xs text-amber-800">
              Ignored columns (not recognised): {result.ignored_columns.join(', ')}
            </p>
          )}
          {step === 'done' && result.failed > 0 && (
            <p className="text-sm text-gray-700">Rows with errors were skipped. Fix them in your file and import it again; rows already imported will show as &ldquo;No change&rdquo;.</p>
          )}
          <label className="inline-flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} className="h-4 w-4 rounded border-gray-300 text-purple-600" />
            Show only rows with errors
          </label>
          <div className="max-h-[45vh] overflow-auto rounded-lg border border-gray-200">
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">Row</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">Employee</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">Result</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((r) => (
                  <tr key={r.row} className="align-top">
                    <td className="px-3 py-2 text-gray-500">{r.row}</td>
                    <td className="px-3 py-2">
                      <p className="text-gray-900">{r.name || '—'}</p>
                      <p className="text-xs text-gray-500">{r.email}</p>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${ACTION_STYLES[r.action].cls}`}>
                        {ACTION_STYLES[r.action].label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-700">
                      {r.errors.length > 0
                        ? r.errors.join(' ')
                        : r.action === 'update'
                          ? `Changes: ${r.changes.map((c) => c.replace('custom:', '').replace(/_/g, ' ')).join(', ')}`
                          : r.action === 'create' && r.invited
                            ? 'Will receive an invite email'
                            : ''}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-500">No rows to show.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
