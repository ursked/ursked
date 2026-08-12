'use client';

import { useState } from 'react';
import { User } from '@/types';

interface SeparationModalProps {
  employee: User;
  onClose: () => void;
  onConfirm: (data: { separation_type: string; separation_date: string; separation_reason?: string }) => Promise<void>;
}

export default function SeparationModal({ employee, onClose, onConfirm }: SeparationModalProps) {
  const [separationType, setSeparationType] = useState<'resigned' | 'terminated'>('resigned');
  const [separationDate, setSeparationDate] = useState(new Date().toISOString().split('T')[0]);
  const [separationReason, setSeparationReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onConfirm({
        separation_type: separationType,
        separation_date: separationDate,
        separation_reason: separationReason || undefined,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Separate Employee</h2>
          <p className="text-sm text-gray-500 mt-1">
            Mark {employee.first_name} {employee.last_name} as resigned or terminated.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
          {/* Separation Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Separation Type</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSeparationType('resigned')}
                className={`relative flex items-center gap-3 rounded-lg border-2 p-4 transition-all ${
                  separationType === 'resigned'
                    ? 'border-orange-500 bg-orange-50 ring-1 ring-orange-500'
                    : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                  separationType === 'resigned' ? 'bg-orange-100' : 'bg-gray-100'
                }`}>
                  <svg className={`w-5 h-5 ${separationType === 'resigned' ? 'text-orange-600' : 'text-gray-500'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                </div>
                <div className="text-left">
                  <p className={`text-sm font-semibold ${separationType === 'resigned' ? 'text-orange-900' : 'text-gray-900'}`}>Resigned</p>
                  <p className="text-xs text-gray-500">Voluntary separation</p>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setSeparationType('terminated')}
                className={`relative flex items-center gap-3 rounded-lg border-2 p-4 transition-all ${
                  separationType === 'terminated'
                    ? 'border-red-500 bg-red-50 ring-1 ring-red-500'
                    : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                  separationType === 'terminated' ? 'bg-red-100' : 'bg-gray-100'
                }`}>
                  <svg className={`w-5 h-5 ${separationType === 'terminated' ? 'text-red-600' : 'text-gray-500'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                  </svg>
                </div>
                <div className="text-left">
                  <p className={`text-sm font-semibold ${separationType === 'terminated' ? 'text-red-900' : 'text-gray-900'}`}>Terminated</p>
                  <p className="text-xs text-gray-500">Involuntary separation</p>
                </div>
              </button>
            </div>
          </div>

          {/* Separation Date */}
          <div>
            <label htmlFor="separation-date" className="block text-sm font-medium text-gray-700 mb-1">
              Separation Date
            </label>
            <input
              id="separation-date"
              type="date"
              required
              value={separationDate}
              onChange={(e) => setSeparationDate(e.target.value)}
              className="block w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm shadow-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-500 focus:outline-none"
            />
          </div>

          {/* Reason */}
          <div>
            <label htmlFor="separation-reason" className="block text-sm font-medium text-gray-700 mb-1">
              Reason <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <textarea
              id="separation-reason"
              rows={3}
              value={separationReason}
              onChange={(e) => setSeparationReason(e.target.value)}
              placeholder="Enter the reason for separation..."
              className="block w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm shadow-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-500 focus:outline-none resize-none"
            />
          </div>

          {/* Info tooltip / notice */}
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
            <div className="flex gap-3">
              <svg className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div className="text-sm text-amber-800">
                <p className="font-medium mb-1">What happens when you separate this employee?</p>
                <ul className="list-disc list-inside space-y-1 text-xs text-amber-700">
                  <li>
                    Marking <strong>{employee.first_name} {employee.last_name}</strong> as{' '}
                    <strong>{separationType}</strong> on <strong>{separationDate}</strong> will deactivate their account.
                  </li>
                  <li>
                    Their data will remain in your tenant database for record-keeping purposes.
                  </li>
                  <li>
                    Succeeding analytics after the configured exclusion period will no longer include this employee in computed metrics.
                  </li>
                  <li>
                    You can configure data retention and analytics exclusion days in <strong>Settings &gt; General</strong>.
                  </li>
                  <li>
                    This action can be reversed by reinstating the employee.
                  </li>
                </ul>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className={`px-4 py-2.5 text-sm font-semibold text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                separationType === 'terminated'
                  ? 'bg-red-600 hover:bg-red-700'
                  : 'bg-orange-600 hover:bg-orange-700'
              }`}
            >
              {submitting ? 'Processing...' : `Confirm ${separationType === 'resigned' ? 'Resignation' : 'Termination'}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
