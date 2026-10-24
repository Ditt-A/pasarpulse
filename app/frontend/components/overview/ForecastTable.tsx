"use client";
import {
  ArrowDown,
  ArrowUp,
  ArrowDownUp,
  ArrowUpRight,
  SearchX,
} from "lucide-react";
import type { Forecast } from "@/lib/types";
import type { RankingOptions } from "@/lib/overview.mjs";
import { idr, pct } from "@/components/common/format";
import { StatusBadge } from "@/components/common/StatusBadge";
interface Props {
  rows: Forecast[];
  selected: string;
  onSelect: (forecast: Forecast) => void;
  sort: NonNullable<RankingOptions["sort"]>;
  direction: "asc" | "desc";
  onSort: (sort: NonNullable<RankingOptions["sort"]>) => void;
  onClear: () => void;
  loading?: boolean;
  horizon: number;
}
export function ForecastTable({
  rows,
  selected,
  onSelect,
  sort,
  direction,
  onSort,
  onClear,
  loading = false,
  horizon,
}: Props) {
  const columns: { key: NonNullable<RankingOptions["sort"]>; label: string }[] =
    [
      { key: "province_name", label: "Provinsi" },
      { key: "current_price", label: "Harga snapshot" },
      { key: "predicted_price", label: `Proyeksi ${horizon} hari` },
      { key: "projected_change_pct", label: "Perubahan" },
    ];
  return (
    <section
      className="forecast-table-pane"
      aria-label="Daftar proyeksi provinsi"
      aria-busy={loading}
    >
      <div className="forecast-scroll scrollbar-thin">
        <table className="data-table forecast-table">
          <caption className="sr-only">
            Harga snapshot dan proyeksi dalam rupiah per kilogram. Pilih
            provinsi untuk membuka detail.
          </caption>
          <thead>
            <tr>
              {columns.map(({ key, label }) => (
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
                  <button onClick={() => onSort(key)}>
                    {label}
                    {sort === key ? (
                      direction === "asc" ? (
                        <ArrowUp size={12} />
                      ) : (
                        <ArrowDown size={12} />
                      )
                    ) : (
                      <ArrowDownUp size={12} />
                    )}
                  </button>
                </th>
              ))}
              <th scope="col">Peringatan</th>
              <th scope="col">
                <span className="sr-only">Buka detail</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 12 }, (_, i) => (
                  <tr key={i} aria-hidden="true">
                    {Array.from({ length: 6 }, (_, j) => (
                      <td key={j}>
                        <div className="skeleton h-3.5 w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((row, index) => (
                  <tr
                    key={row.forecast_id}
                    aria-selected={selected === row.province_code}
                    onClick={() => onSelect(row)}
                  >
                    <td>
                      <button
                        className="province-name"
                        data-province={row.province_code}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(row);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                            e.preventDefault();
                            const tr = e.currentTarget.closest("tr");
                            const next =
                              e.key === "ArrowDown"
                                ? tr?.nextElementSibling
                                : tr?.previousElementSibling;
                            (
                              next?.querySelector(
                                ".province-name",
                              ) as HTMLButtonElement | null
                            )?.focus();
                          }
                        }}
                      >
                        <span className="province-index">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        {row.province_name}
                      </button>
                    </td>
                    <td className="current-price">{idr(row.current_price)}</td>
                    <td className="forecast-price">
                      {idr(row.predicted_price)}
                    </td>
                    <td
                      className={
                        row.projected_change_pct > 0
                          ? "change-up"
                          : "change-down"
                      }
                    >
                      {pct(row.projected_change_pct)}
                    </td>
                    <td>
                      <StatusBadge label={row.warning_level} />
                    </td>
                    <td>
                      <ArrowUpRight
                        size={14}
                        className="row-arrow"
                        aria-hidden="true"
                      />
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
        {!loading && !rows.length && (
          <div className="empty-state">
            <SearchX size={25} />
            <h2>Tidak ada hasil</h2>
            <p>Coba nama provinsi atau tingkat peringatan lain.</p>
            <button className="ui-button mt-4" onClick={onClear}>
              Hapus filter daftar
            </button>
          </div>
        )}
      </div>
      <div className="table-bottom">
        <span aria-live="polite">
          {loading ? "Memuat data…" : `${rows.length} provinsi ditampilkan`}
        </span>
        <span>Harga dalam Rp/kg</span>
      </div>
    </section>
  );
}
