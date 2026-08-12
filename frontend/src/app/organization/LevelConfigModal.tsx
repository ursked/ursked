'use client';

import { useState } from 'react';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { OrgLevel } from '@/types';

interface Props {
  currentLevels: OrgLevel[];
  onClose: () => void;
  onSaved: () => void;
}

interface LevelDraft {
  level_number: number;
  name: string;
}

export default function LevelConfigModal({ currentLevels, onClose, onSaved }: Props) {
  const { showToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [levels, setLevels] = useState<LevelDraft[]>(
    currentLevels.length > 0
      ? currentLevels.map(l => ({ level_number: l.level_number, name: l.name }))
      : [{ level_number: 1, name: '' }]
  );

  // No upper bound: some organizations are very deep.
  const canRemoveLevel = levels.length > 1;

  const handleAddLevel = () => {
    const nextNum = levels.length + 1;
    setLevels([...levels, { level_number: nextNum, name: '' }]);
  };

  const handleRemoveLevel = (index: number) => {
    if (!canRemoveLevel) return;
    const updated = levels
      .filter((_, i) => i !== index)
      .map((l, i) => ({ ...l, level_number: i + 1 }));
    setLevels(updated);
  };

  const handleNameChange = (index: number, name: string) => {
    const updated = [...levels];
    updated[index] = { ...updated[index], name };
    setLevels(updated);
  };

  const handleSave = async () => {
    // Validate
    for (const l of levels) {
      if (!l.name.trim()) {
        showToast('All level names are required', 'error');
        return;
      }
    }

    setSaving(true);
    try {
      await api.setOrgLevels(levels.map(l => ({ level_number: l.level_number, name: l.name.trim() })));
      onSaved();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to save levels';
      showToast(message, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">Configure Organization Levels</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          <p className="text-sm text-gray-500">
            Define your organization hierarchy levels from top to bottom (e.g., Department → Division → Section).
            Add as many levels as your organization needs — from a flat structure to a deep hierarchy.
          </p>

          <div className="space-y-3">
            {levels.map((level, index) => (
              <div key={index} className="flex items-center gap-3">
                <span className="w-8 h-8 flex-shrink-0 rounded-full bg-purple-100 text-purple-700 text-sm font-semibold flex items-center justify-center">
                  {level.level_number}
                </span>
                <input
                  type="text"
                  value={level.name}
                  onChange={(e) => handleNameChange(index, e.target.value)}
                  placeholder={`Level ${level.level_number} name (e.g., ${['Department', 'Division', 'Section', 'Unit', 'Team', 'Group', 'Sub-group', 'Cell', 'Squad'][index] || `Sub-level ${level.level_number}`})`}
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
                  maxLength={100}
                />
                {canRemoveLevel && (
                  <button
                    onClick={() => handleRemoveLevel(index)}
                    className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                    title="Remove level"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                )}
              </div>
            ))}
          </div>

          <button
            onClick={handleAddLevel}
            className="w-full py-2 border-2 border-dashed border-gray-300 rounded-lg text-sm font-medium text-gray-500 hover:text-purple-600 hover:border-purple-300 transition-colors flex items-center justify-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Level ({levels.length})
          </button>

          {levels.length > 1 && (
            <div className="flex items-center gap-2 text-xs text-gray-400 mt-2">
              <span>Hierarchy:</span>
              {levels.map((l, i) => (
                <span key={i}>
                  <span className="font-medium text-gray-500">{l.name || `Level ${l.level_number}`}</span>
                  {i < levels.length - 1 && <span className="mx-1">→</span>}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t bg-gray-50 rounded-b-xl">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {saving && (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            Save Levels
          </button>
        </div>
      </div>
    </div>
  );
}
