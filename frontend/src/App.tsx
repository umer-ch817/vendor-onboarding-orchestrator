/** Route table and application shell wiring.
 *
 * The eight operational views in §21 all hang off the persistent Layout, so a
 * reviewer keeps their queue context while drilling into a case.
 */

import { useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { DashboardPage } from './pages/DashboardPage';
import { VendorCasesPage } from './pages/VendorCasesPage';
import { VendorDetailPage } from './pages/VendorDetailPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { DocumentDetailPage } from './pages/DocumentDetailPage';
import { RiskReviewPage } from './pages/RiskReviewPage';
import { ExceptionQueuePage } from './pages/ExceptionQueuePage';
import { ApprovalQueuePage } from './pages/ApprovalQueuePage';
import { AuditTimelinePage } from './pages/AuditTimelinePage';
import { SettingsPage } from './pages/SettingsPage';

export default function App() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Routes>
      <Route
        element={
          <Layout
            collapsed={collapsed}
            onToggleCollapse={() => setCollapsed((c) => !c)}
          />
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/cases" element={<VendorCasesPage />} />
        <Route path="/cases/:caseId" element={<VendorDetailPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
        <Route path="/risk" element={<RiskReviewPage />} />
        <Route path="/risk/case/:caseId" element={<RiskReviewPage />} />
        <Route path="/exceptions" element={<ExceptionQueuePage />} />
        <Route path="/approvals" element={<ApprovalQueuePage />} />
        <Route path="/audit" element={<AuditTimelinePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
