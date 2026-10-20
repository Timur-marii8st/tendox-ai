import { existsSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const webRoot = resolve(repositoryRoot, "web");
const testsRoot = resolve(webRoot, "tests");
const buildRoot = resolve(webRoot, "build");

function fail(message) {
  console.error(`web test inventory error: ${message}`);
  process.exit(1);
}

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

function webRelative(path) {
  return relative(webRoot, path).split(sep).join("/");
}

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: webRoot,
    encoding: "utf8",
    stdio: "inherit",
  });
  if (result.error) {
    fail(`${command} could not start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const configs = readdirSync(webRoot)
  .filter((name) => /^tsconfig\..+-tests\.json$/.test(name))
  .sort();
if (configs.length === 0) {
  fail("no tsconfig.*-tests.json files found");
}

const actualTests = walk(testsRoot)
  .map(webRelative)
  .filter((name) => /\.test\.tsx?$/.test(name))
  .sort();
const owners = new Map(actualTests.map((name) => [name, []]));
const emittedTests = [];
const outDirs = [];

for (const configName of configs) {
  const config = JSON.parse(readFileSync(resolve(webRoot, configName), "utf8"));
  const includes = config.include ?? [];
  const tests = includes.filter((name) => /\.test\.tsx?$/.test(name));
  if (tests.length === 0) {
    fail(`${configName} does not include a test source`);
  }
  for (const included of includes) {
    if (!existsSync(resolve(webRoot, included))) {
      fail(`${configName} references missing file ${included}`);
    }
  }
  for (const test of tests) {
    if (!owners.has(test)) {
      fail(`${configName} includes untracked test path ${test}`);
    }
    owners.get(test).push(configName);
  }

  const outDir = config.compilerOptions?.outDir;
  const resolvedOutDir = typeof outDir === "string" ? resolve(webRoot, outDir) : "";
  if (
    !resolvedOutDir ||
    resolvedOutDir === buildRoot ||
    !resolvedOutDir.startsWith(buildRoot + sep)
  ) {
    fail(`${configName} outDir must be a strict descendant of web/build`);
  }
  if (
    outDirs.some(
      (existing) =>
        resolvedOutDir === existing ||
        resolvedOutDir.startsWith(existing + sep) ||
        existing.startsWith(resolvedOutDir + sep),
    )
  ) {
    fail(`${configName} outDir overlaps another test output directory`);
  }
  outDirs.push(resolvedOutDir);
  rmSync(resolvedOutDir, { recursive: true, force: true });

  const tsc = resolve(webRoot, "node_modules", "typescript", "bin", "tsc");
  run(process.execPath, [tsc, "-p", configName]);
  emittedTests.push(
    ...tests.map((test) =>
      resolve(webRoot, outDir, test.replace(/\.tsx?$/, ".js")),
    ),
  );
}

for (const [test, assignedConfigs] of owners) {
  if (assignedConfigs.length !== 1) {
    fail(`${test} is covered by ${assignedConfigs.length} configs: ${assignedConfigs.join(", ")}`);
  }
}
for (const test of emittedTests) {
  if (!existsSync(test)) {
    fail(`TypeScript did not emit ${webRelative(test)}`);
  }
}

console.log(
  `Running ${emittedTests.length} compiled Node wire/render tests from ${configs.length} configs.`,
);
console.log("Browser/E2E tests: NOT_PERFORMED (no browser suite is configured in this gate).\n");
run(process.execPath, ["--test", ...emittedTests]);
