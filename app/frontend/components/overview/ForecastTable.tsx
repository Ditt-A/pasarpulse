"use client";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownUp,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Search,
  SearchX,
  X,
} from "lucide-react";
import type { Forecast } from "@/lib/types";
import { rankForecasts, type RankingOptions } from "@/lib/overview.mjs";
import { idr, pct } from "@/components/common/format";
import { StatusBadge } from "@/components/common/StatusBadge";

export function ForecastTable({
  rows,
  selected,
  onSelect,
}: {
  rows: Forecast[];
  selected: string;
  onSelect: (forecast: Forecast) => void;
}) {
  const [search, setSearch] = useState("");
  const [warning, setWarning] = useState("ALL");
  const [sort, setSort] = useState<RankingOptions["sort"]>(
    "projected_change_pct",
  );
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [search, warning, rows]);
  const ranked = useMemo(
    () => rankForecasts(rows, { search, warning, sort, direction }),
    [rows, search, warning, sort, direction],
  );
  const pages = Math.max(1, Math.ceil(ranked.length / 8));
  const activePage = Math.min(page, pages - 1);
  const visible = ranked.slice(activePage * 8, activePage * 8 + 8);
  const changeSort = (key: RankingOptions["sort"]) => {
    setSort(key);
    setDirection(sort === key && direction === "desc" ? "asc" : "desc");
    setPage(0);
  };
  const headings: {
    key: NonNullable<RankingOptions["sort"]>;
    label: string;
  }[] = [
    { key: "province_name", label: "Province" },
    { key: "current_price", label: "Current price / kg" },
    { key: "predicted_price", label: "Forecast / kg" },
    { key: "projected_change_pct", label: "Projected change" },
  ];
  return (
    <section className="surface" aria-label="Province forecasts">
      <div className="surface-heading">
        <div>
          <h2>Across the provinces</h2>
          <p>
            Compare prices for the selected commodity, market, and forecast
            horizon.
          </p>
          <p className="sm:hidden">
            Swipe the table for more, or select a province.
          </p>
        </div>
        <span className="eyebrow hidden sm:inline">
          {rows.length} forecasts
        </span>
      </div>
      <div className="table-toolbar">
        <div className="table-tabs" aria-label="Filter by warning">
          {["ALL", "HIGH", "ELEVATED", "WATCH", "STABLE"].map((level) => (
            <button
              key={level}
              aria-pressed={warning === level}
              onClick={() => setWarning(level)}
            >
              {level === "ALL"
                ? "All provinces"
                : level.charAt(0) + level.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
        <label className="search-field">
          <Search size={14} />
          <input
            aria-label="Search provinces"
            placeholder="Find a province…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {search && (
            <button
              aria-label="Clear province search"
              onClick={() => setSearch("")}
            >
              <X size={13} />
            </button>
          )}
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <caption className="sr-only">
            Province-level point forecasts. Prices are in Indonesian rupiah per
            kilogram.
          </caption>
          <thead>
            <tr>
              {headings.map(({ key, label }) => (
                <th
                  key={key}
                  scope="col"
                  aria-sort={
                    sort === key
                      ? direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button onClick={() => changeSort(key)}>
                    {label}
                    <ArrowDownUp size={11} />
                  </button>
                </th>
              ))}
              <th scope="col">Warning</th>
              <th scope="col">
                <span className="sr-only">Open forecast</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr
                key={row.forecast_id}
                aria-selected={selected === row.province_code}
              >
                <td>
                  <button
                    className="province-name"
                    onClick={() => onSelect(row)}
                  >
                    <span className="province-index">
                      {String(activePage * 8 + index + 1).padStart(2, "0")}
                    </span>
                    {row.province_name}
                  </button>
                </td>
                <td className="text-[#73816c]">{idr(row.current_price)}</td>
                <td className="font-medium">{idr(row.predicted_price)}</td>
                <td
                  className={
                    row.projected_change_pct > 0 ? "change-up" : "change-down"
                  }
                >
                  {pct(row.projected_change_pct)}
                </td>
                <td>
                  <StatusBadge label={row.warning_level} />
                </td>
                <td>
                  <button
                    className="text-[#789273]"
                    aria-label={`Open forecast for ${row.province_name}`}
                    onClick={() => onSelect(row)}
                  >
                    <ArrowUpRight size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!visible.length && (
        <div className="empty-state">
          <SearchX size={25} />
          <h2>No provinces match</h2>
          <p>Try another name or warning level.</p>
          <button
            className="ui-link mt-4"
            onClick={() => {
              setSearch("");
              setWarning("ALL");
            }}
          >
            Clear filters
          </button>
        </div>
      )}
      <div className="table-pagination">
        <span aria-live="polite">
          {ranked.length
            ? `${activePage * 8 + 1}–${Math.min((activePage + 1) * 8, ranked.length)} of ${ranked.length} provinces`
            : "0 provinces"}
        </span>
        <div className="pagination-actions">
          <button
            className="ui-button icon-only"
            aria-label="Previous page"
            disabled={activePage === 0}
            onClick={() => setPage(activePage - 1)}
          >
            <ChevronLeft size={13} />
          </button>
          <span>
            {activePage + 1} / {pages}
          </span>
          <button
            className="ui-button icon-only"
            aria-label="Next page"
            disabled={activePage + 1 >= pages}
            onClick={() => setPage(activePage + 1)}
          >
            <ChevronRight size={13} />
          </button>
        </div>
      </div>
    </section>
  );
}
