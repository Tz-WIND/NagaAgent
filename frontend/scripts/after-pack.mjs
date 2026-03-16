import { existsSync } from "node:fs";
import { join } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

async function run(cmd, args) {
  const { stdout, stderr } = await execFileAsync(cmd, args);
  if (stdout.trim()) {
    process.stdout.write(stdout);
  }
  if (stderr.trim()) {
    process.stderr.write(stderr);
  }
}

export default async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") {
    return;
  }

  const appPath = join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
  );
  if (!existsSync(appPath)) {
    throw new Error(`[afterPack] app not found: ${appPath}`);
  }

  process.stdout.write(`[afterPack] ad-hoc signing ${appPath}\n`);
  await run("codesign", ["--force", "--deep", "--sign", "-", appPath]);
  await run("codesign", ["--verify", "--deep", "--strict", "--verbose=2", appPath]);
}
