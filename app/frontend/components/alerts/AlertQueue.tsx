"use client";
import { ArrowUpRight } from "lucide-react";
import type { Alert } from "@/lib/types";
import { idr, pct } from "@/components/common/format";
import { StatusBadge } from "@/components/common/StatusBadge";
export function AlertQueue({
  alerts,
  onSelect,
  compact = false,
}: {
  alerts: Alert[];
  onSelect?: (alert: Alert) => void;
  compact?: boolean;
}) {
  return (
    <section className="surface">
      <div className="surface-heading">
        <div>
          <h2>Monitoring queue</h2>
          <p>
            Open a province to inspect its forecast and supporting evidence.
          </p>
        </div>
        <span className="eyebrow">{alerts.length} results</span>
      </div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <caption className="sr-only">
            Forecasts ordered by monitoring priority
          </caption>
          <thead>
            <tr>
              <th scope="col">Priority</th>
              <th scope="col">Province</th>
              <th scope="col">Current / kg</th>
              <th scope="col">Forecast / kg</th>
              <th scope="col">Projected change</th>
              <th scope="col">Warning</th>
              <th scope="col">
                <span className="sr-only">Open forecast</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {alerts.slice(0, compact ? 8 : 100).map((alert) => (
              <tr key={alert.alert_id}>
                <td className="text-[#94a18a]">
                  {String(alert.priority).padStart(2, "0")}
                </td>
                <td>
                  <button
                    className="province-name"
                    onClick={() => onSelect?.(alert)}
                  >
                    {alert.province_name}
                  </button>
                </td>
                <td className="text-[#72816a]">{idr(alert.current_price)}</td>
                <td className="font-medium">{idr(alert.predicted_price)}</td>
                <td
                  className={
                    alert.projected_change_pct > 0 ? "change-up" : "change-down"
                  }
                >
                  {pct(alert.projected_change_pct)}
                </td>
                <td>
                  <StatusBadge label={alert.warning_level} />
                </td>
                <td>
                  <button
                    aria-label={`Inspect ${alert.province_name}`}
                    className="text-cyanpulse"
                    onClick={() => onSelect?.(alert)}
                  >
                    <ArrowUpRight size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!alerts.length && (
        <div className="empty-state">
          <h2>No forecasts at this warning level</h2>
          <p>Choose another level or adjust the forecast context.</p>
        </div>
      )}
    </section>
  );
}
