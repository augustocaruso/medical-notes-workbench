import { commandFromPayload, parseMedOpsCommand, resolveManifest } from "./commands.mjs";
import { loadDryRunState, saveDryRunState, sha256File } from "./receipts.mjs";
import { publishDryRunTtlMs, quiet, responseConfirmsDryRun, toolSucceeded } from "./runtime.mjs";

export async function medOpsBefore(payload) {
  const command = commandFromPayload(payload);
  const parsed = parseMedOpsCommand(command);
  if (!parsed) return quiet();

  if (parsed.subcommand === "commit") {
    return {
      decision: "deny",
      reason:
        "Bloqueado: o comando legado med_ops.py commit foi removido. Use stage-note, depois publish-batch --dry-run e só então publish-batch.",
      suppressOutput: true,
    };
  }

  if (parsed.subcommand === "commit-batch" && !parsed.dryRun) {
    return {
      decision: "deny",
      reason:
        "Bloqueado: commit-batch é apenas alias de compatibilidade. Use publish-batch --dry-run, revise, depois publish-batch.",
      suppressOutput: true,
    };
  }

  if (parsed.subcommand !== "publish-batch" || parsed.dryRun) return quiet();

  const manifestPath = resolveManifest(parsed.manifest, payload.cwd);
  if (!manifestPath) {
    return {
      decision: "deny",
      reason: "Bloqueado: publish-batch real precisa de --manifest para validar o dry-run anterior.",
      suppressOutput: true,
    };
  }

  let manifestSha;
  try {
    manifestSha = await sha256File(manifestPath);
  } catch {
    return {
      decision: "deny",
      reason:
        "Bloqueado: nao consegui ler o manifest informado. Confirme o caminho e rode publish-batch --dry-run novamente.",
      suppressOutput: true,
    };
  }

  const state = await loadDryRunState();
  const receipt = state.receipts?.[manifestPath];
  if (!receipt) {
    return {
      decision: "deny",
      reason: "Bloqueado: rode publish-batch --dry-run para este manifest antes do publish real.",
      suppressOutput: true,
    };
  }
  if (Date.now() > Number(receipt.expires_at || 0)) {
    return {
      decision: "deny",
      reason: "Bloqueado: o dry-run desse manifest expirou. Rode publish-batch --dry-run novamente.",
      suppressOutput: true,
    };
  }
  if (receipt.manifest_sha256 !== manifestSha) {
    return {
      decision: "deny",
      reason: "Bloqueado: o manifest mudou desde o dry-run. Rode publish-batch --dry-run novamente.",
      suppressOutput: true,
    };
  }

  return quiet();
}

export async function medOpsAfter(payload) {
  const command = commandFromPayload(payload);
  const parsed = parseMedOpsCommand(command);
  if (!parsed || parsed.subcommand !== "publish-batch") return quiet();

  const manifestPath = resolveManifest(parsed.manifest, payload.cwd);
  if (!manifestPath || !toolSucceeded(payload)) return quiet();

  const state = await loadDryRunState();
  state.receipts ||= {};

  if (parsed.dryRun) {
    if (!responseConfirmsDryRun(payload)) {
      return {
        systemMessage:
          "Dry-run terminou, mas o hook nao encontrou confirmacao JSON de dry_run=true. O publish-batch real continuara bloqueado.",
        suppressOutput: true,
      };
    }

    const manifestSha = await sha256File(manifestPath);
    const now = Date.now();
    state.receipts[manifestPath] = {
      manifest: manifestPath,
      manifest_sha256: manifestSha,
      cwd: payload.cwd || process.cwd(),
      dry_run_at: new Date(now).toISOString(),
      expires_at: now + publishDryRunTtlMs,
    };
    await saveDryRunState(state);
    return {
      systemMessage: "Dry-run validado para este manifest; publish-batch real liberado por tempo limitado.",
      suppressOutput: true,
    };
  }

  if (state.receipts[manifestPath]) {
    delete state.receipts[manifestPath];
    await saveDryRunState(state);
    return {
      systemMessage: "Publish-batch concluido; o recibo de dry-run deste manifest foi invalidado.",
      suppressOutput: true,
    };
  }

  return quiet();
}
