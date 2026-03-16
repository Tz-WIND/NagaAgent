import { access } from "node:fs/promises";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REMAP_SUFFIXES = new Map([
  [".js", [".ts", ".tsx"]],
  [".mjs", [".mts", ".ts", ".tsx"]],
  [".cjs", [".cts", ".ts", ".tsx"]],
]);

async function fileExists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

function isRelativePath(specifier) {
  return specifier.startsWith("./") || specifier.startsWith("../");
}

function remapSuffixes(specifier) {
  for (const [suffix, replacements] of REMAP_SUFFIXES.entries()) {
    if (!specifier.endsWith(suffix)) {
      continue;
    }
    const base = specifier.slice(0, -suffix.length);
    return replacements.map((replacement) => `${base}${replacement}`);
  }
  return [];
}

export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (error?.code !== "ERR_MODULE_NOT_FOUND") {
      throw error;
    }
    if (!context.parentURL || !isRelativePath(specifier)) {
      throw error;
    }

    const parentDir = dirname(fileURLToPath(context.parentURL));
    for (const candidateSpecifier of remapSuffixes(specifier)) {
      const candidatePath = resolvePath(parentDir, candidateSpecifier);
      if (!(await fileExists(candidatePath))) {
        continue;
      }
      return {
        shortCircuit: true,
        url: pathToFileURL(candidatePath).href,
      };
    }
    throw error;
  }
}
