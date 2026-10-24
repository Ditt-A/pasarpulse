"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Info } from "lucide-react";
import { api } from "@/lib/api";
import catalog from "@/lib/data-catalog.json";
import { idr } from "@/components/common/format";
import { RequestState } from "@/components/common/RequestState";
const groupNames: Record<string, string> = {
  multimodal_ablation: "Ablasi multimodal tervalidasi",
  saved_a100_search: "Pencarian arsitektur A100",
  compact_visible_rerun: "Uji ulang ringkas",
  prior_fold_meta: "Meta-model fold terdahulu",
  a100_experiment: "Eksperimen A100",
  proposal_named_tree_variant: "Varian tree pada proposal",
  diagnostic_same_fold_weighting: "Diagnostik bobot pada fold yang sama",
};
const tabs = [
  { key: "data", label: "Sumber data" },
  { key: "models", label: "Model & hasil" },
  { key: "validation", label: "Validasi" },
];
export default function ModelPage() {
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  const benchmarks = useQuery({
    queryKey: ["benchmarks"],
    queryFn: api.benchmarks,
  });
  const [tab, setTab] = useState("data"),
    [group, setGroup] = useState("multimodal_ablation"),
    [horizon, setHorizon] = useState("ALL");
  const groups = useMemo(
    () =>
      Array.from(new Set((benchmarks.data?.rows || []).map((x) => x.group))),
    [benchmarks.data],
  );
  const rows = useMemo(
    () =>
      (benchmarks.data?.rows || [])
        .filter(
          (row) =>
            row.group === group &&
            (horizon === "ALL" || row.horizon_days === Number(horizon)),
        )
        .sort(
          (a, b) =>
            (a.horizon_days || 0) - (b.horizon_days || 0) ||
            a.mae_idr_per_kg - b.mae_idr_per_kg,
        ),
    [benchmarks.data, group, horizon],
  );
  const winners = [7, 14].map((days) =>
    benchmarks.data?.rows.find(
      (row) =>
        row.group === "multimodal_ablation" &&
        row.horizon_days === days &&
        metadata.data?.models.includes(row.model),
    ),
  );
  if (metadata.isError)
    return <RequestState error retry={() => void metadata.refetch()} />;
  if (!metadata.data) return <RequestState />;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Data & metode</h1>
          <p>
            Sumber, pemakaian fitur, dan hasil validasi untuk proyeksi
            PasarPulse.
          </p>
        </div>
      </div>
      <div className="method-tabs" role="tablist" aria-label="Data dan metode">
        {tabs.map((item, index) => (
          <button
            role="tab"
            id={`method-${item.key}`}
            aria-controls="method-content"
            aria-selected={tab === item.key}
            tabIndex={tab === item.key ? 0 : -1}
            key={item.key}
            onClick={() => setTab(item.key)}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                e.preventDefault();
                const next =
                  tabs[
                    (index + (e.key === "ArrowRight" ? 1 : 2)) % tabs.length
                  ];
                setTab(next.key);
                document.getElementById(`method-${next.key}`)?.focus();
              }
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <section
        id="method-content"
        role="tabpanel"
        aria-labelledby={`method-${tab}`}
      >
        {tab === "data" && (
          <>
            <p className="data-intro">
              Riset menggabungkan <strong>enam kelompok data</strong> dengan
              fitur graph ketergantungan harga. Model 7 hari terpilih memakai
              semua kelompok dan graph dinamis. Model 14 hari terpilih memakai{" "}
              <strong>harga dan kalender</strong>; data lainnya tetap dapat
              ditampilkan sebagai konteks.
            </p>
            <section className="surface">
              <div className="overflow-x-auto">
                <table className="data-table modality-table">
                  <caption className="sr-only">
                    Enam modalitas dan penggunaannya pada model replay yang
                    terpilih.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Kelompok data</th>
                      <th scope="col">Sumber</th>
                      <th scope="col">Informasi yang digunakan</th>
                      <th scope="col">Model terpilih</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.modalities.map((item) => (
                      <tr key={item.id}>
                        <td className="font-medium text-[#29352e]">
                          {item.name}
                        </td>
                        <td className="text-[#65726a]">{item.source}</td>
                        <td className="text-[#65726a]">{item.description}</td>
                        <td>
                          <ModelUse days14={item.days14} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="mt-6 grid gap-5 lg:grid-cols-2">
              <article className="surface p-5">
                <h2 className="text-sm font-semibold">
                  Graph dinamis sebagai fitur tambahan
                </h2>
                <p className="method-note !mb-0">
                  {catalog.dynamicGraph.description} Fitur ini digunakan model 7
                  hari; pada model 14 hari berperan sebagai konteks tambahan.
                </p>
              </article>
              <article className="surface p-5">
                <h2 className="text-sm font-semibold">
                  Cakupan dan data yang tidak tersedia
                </h2>
                <p className="method-note !mb-0">
                  Geometri BIG mencakup{" "}
                  {metadata.data.province_count_in_geometry} provinsi. Arsip
                  proyeksi mencakup {metadata.data.province_count_in_forecast}{" "}
                  kode provinsi; jumlah pada tiap filter dapat lebih kecil. Data
                  hilang tetap ditandai, bukan diisi dengan prediksi provinsi
                  lain.
                </p>
              </article>
            </section>
            <p className="method-note">
              <strong>Arsip SP2KP:</strong> 30 unduhan tersedia di repo, tetapi
              manifest mencatat kegagalan parsing. Snapshot harga dan proyeksi
              yang ditampilkan menggunakan PIHPS.
            </p>
            <div className="notice">
              <Info size={14} />
              <span>
                Dashboard menyajikan snapshot historis dan data pendukung yang
                disimpan. Interaksi tidak memuat bobot model, melatih ulang,
                atau mengambil ulang data dari penyedia.
              </span>
            </div>
          </>
        )}
        {tab === "models" &&
          (benchmarks.isError ? (
            <RequestState error retry={() => void benchmarks.refetch()} />
          ) : !benchmarks.data ? (
            <RequestState />
          ) : (
            <>
              <dl className="metric-strip">
                {winners.map((row, i) => (
                  <div key={i}>
                    <dt>MAE model replay {i === 0 ? 7 : 14} hari</dt>
                    <dd>
                      {row ? idr(row.mae_idr_per_kg) : "—"}
                      <small>/ kg</small>
                    </dd>
                  </div>
                ))}
                <div>
                  <dt>Origin evaluasi kronologis</dt>
                  <dd>
                    {metadata.data.forecast_origins.length}
                    <small>origin</small>
                  </dd>
                </div>
              </dl>
              <p className="data-intro">
                Model replay berasal dari pemenang studi ablasi multimodal,
                bukan skor terbaik dari keluarga eksperimen lain. Hasil
                pencarian A100, uji ulang ringkas, dan meta-model tetap
                dipisahkan.
              </p>
              <section className="surface">
                <div className="table-toolbar">
                  <label className="flex min-w-0 flex-wrap items-center gap-3 text-xs text-[#68736c]">
                    Keluarga hasil
                    <select
                      aria-label="Keluarga hasil benchmark"
                      className="warning-select !max-w-full"
                      value={group}
                      onChange={(e) => setGroup(e.target.value)}
                    >
                      {groups.map((item) => (
                        <option key={item} value={item}>
                          {groupNames[item] || item}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="segmented" aria-label="Horizon benchmark">
                    {["ALL", "7", "14"].map((value) => (
                      <button
                        key={value}
                        aria-pressed={horizon === value}
                        onClick={() => setHorizon(value)}
                      >
                        {value === "ALL" ? "Semua" : `${value} hari`}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <caption className="sr-only">
                      Hasil benchmark tersimpan; MAE lebih kecil berarti galat
                      rata-rata lebih kecil.
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Model</th>
                        <th scope="col">Horizon</th>
                        <th scope="col">MAE / kg</th>
                        <th scope="col">Pemakaian</th>
                        <th scope="col">Sumber</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, i) => (
                        <tr key={`${row.model}-${i}`}>
                          <td className="max-w-[370px] !whitespace-normal break-words text-xs font-medium">
                            {row.model}
                          </td>
                          <td>
                            {row.horizon_days
                              ? `${row.horizon_days} hari`
                              : "—"}
                          </td>
                          <td className="font-semibold">
                            {idr(row.mae_idr_per_kg)}
                          </td>
                          <td className="text-xs">
                            {row.headline_eligible
                              ? "Dapat dibandingkan"
                              : "Diagnostik saja"}
                          </td>
                          <td className="max-w-[330px] !whitespace-normal text-xs text-[#68736c]">
                            <code className="break-all">{row.source_file}</code>
                            <p className="mt-1">{row.note}</p>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!rows.length && (
                  <div className="empty-state">
                    Tidak ada hasil untuk filter ini.
                  </div>
                )}
                <div className="table-bottom">
                  <span>{rows.length} hasil tersimpan</span>
                  <span>MAE lebih rendah lebih baik</span>
                </div>
              </section>
            </>
          ))}
        {tab === "validation" && (
          <>
            <div className="grid gap-5 md:grid-cols-2">
              <article className="surface p-5">
                <h2 className="mb-4 text-sm font-semibold">
                  Informasi mengikuti tanggal snapshot
                </h2>
                <ul className="space-y-3 text-[13px] leading-relaxed text-[#68736c]">
                  {[
                    "Label pelatihan harus tersedia sebelum origin: tanggal + horizon ≤ origin.",
                    "Ketersediaan cuaca, produksi, satelit, dan graph diperiksa terhadap tanggal efektif sumber.",
                    "Peringatan, urutan wilayah, dan ekspor memakai harga snapshot dan proyeksi.",
                    "Harga aktual masa depan hanya tampil setelah pengguna membuka evaluasi historis.",
                  ].map((text) => (
                    <li key={text} className="flex gap-2">
                      <Check
                        size={14}
                        className="mt-1 shrink-0 text-cyanpulse"
                      />
                      {text}
                    </li>
                  ))}
                </ul>
              </article>
              <article className="surface p-5">
                <h2 className="mb-4 text-sm font-semibold">
                  Tingkat peringatan adalah aturan pemantauan
                </h2>
                <p className="text-[13px] leading-relaxed text-[#68736c]">
                  Model memperkirakan harga. Kenaikan proyeksi kemudian
                  dikelompokkan sesuai batas produk berikut.
                </p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  {[
                    ["Stabil", `< ${metadata.data.warning_thresholds.watch}%`],
                    [
                      "Waspada",
                      `${metadata.data.warning_thresholds.watch}%–<${metadata.data.warning_thresholds.elevated}%`,
                    ],
                    [
                      "Meningkat",
                      `${metadata.data.warning_thresholds.elevated}%–<${metadata.data.warning_thresholds.high}%`,
                    ],
                    ["Tinggi", `≥ ${metadata.data.warning_thresholds.high}%`],
                  ].map(([label, value]) => (
                    <div key={label} className="border-t border-line pt-3">
                      <dt className="text-[#68736c]">{label}</dt>
                      <dd className="mt-1 font-medium">{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="method-note !mb-0">
                  Batas tersebut bukan probabilitas model atau ambang regulasi
                  resmi.
                </p>
              </article>
            </div>
            <details className="surface mt-5 p-5">
              <summary className="text-[13px] font-medium">
                Batas interpretasi hasil riset
              </summary>
              <div className="mt-4 space-y-3 text-[13px] leading-relaxed text-[#68736c]">
                <p>
                  Vegetasi satelit adalah proksi regional; produksi tahunan
                  adalah konteks struktural. Keduanya bukan ukuran langsung
                  pasokan harian. Koneksi graph tidak membuktikan arus barang
                  atau sebab-akibat.
                </p>
                <p>
                  Kontribusi fitur LightGBM yang tersimpan berada dalam skala
                  log-ratio, bukan pengaruh kausal atau nominal rupiah. GNN,
                  probabilitas shock, interval ketidakpastian, TFT/TCN, serta
                  CNN/ViT tetap merupakan rancangan penelitian.
                </p>
                <p>
                  Blend inverse-MAE dengan bobot dari fold evaluasi yang sama
                  bersifat diagnostik dan tidak digunakan sebagai hasil utama
                  yang bebas kebocoran.
                </p>
              </div>
            </details>
          </>
        )}
      </section>
    </>
  );
}
function ModelUse({ days14 }: { days14: boolean }) {
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-[#355f46]">
        <Check size={12} />7 hari: fitur model
      </p>
      <p className={days14 ? "text-[#355f46]" : "text-[#7b837e]"}>
        14 hari: {days14 ? "fitur model" : "konteks tambahan"}
      </p>
    </div>
  );
}
