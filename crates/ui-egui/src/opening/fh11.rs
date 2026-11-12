//! Private desktop integration with a locally configured FreeHand MX converter.

use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;
use vectorcraft_engine::cancel;
use vectorcraft_engine::cmd::fileio;

use crate::services::FileFilter;
use crate::{FilePick, VectorcraftApp};

const LIMIT: u64 = 512 << 20;
const TIMEOUT: Duration = Duration::from_secs(360);

pub(crate) fn matches(path: &str) -> bool {
    Path::new(path).extension().and_then(|ext| ext.to_str()).is_some_and(|ext| ext.eq_ignore_ascii_case("fh11"))
}

pub(crate) fn configured() -> Option<PathBuf> {
    std::env::var_os("VECTORCRAFT_FH11_CONVERTER").filter(|path| !path.is_empty()).map(PathBuf::from)
}

pub(crate) fn open_filters(mut filters: Vec<FileFilter>) -> Vec<FileFilter> {
    if configured().is_some() {
        if let Some((_, extensions)) = filters.first_mut() {
            extensions.push("fh11".into());
        }
        filters.push(FilePick::filter("FreeHand MX", &["fh11"]));
    }
    filters
}

pub(crate) fn start(app: &mut VectorcraftApp, path: &str, converter: PathBuf) -> Result<Value, String> {
    let source = fs::canonicalize(path).map_err(|e| e.to_string())?;
    let title = source.file_stem().ok_or("The FreeHand file has no name.")?.to_string_lossy().into_owned();
    let name = format!("{title}.vectorcraft");
    let low_res_proxy_eps = app.session.prefs.low_res_proxy_eps;
    super::start_read(app, path, move || {
        let bytes = convert(&converter, &source)?;
        // The source is a FreeHand file. Open the result with no save path so Save prompts
        // for a new VectorCraft document instead of replacing the source.
        fileio::read_for_open(&name, &bytes, None, &Value::Null, false, low_res_proxy_eps)
            .map(|file| file.with_title(title))
            .map_err(|e| e.to_string())
    })
}

fn convert(converter: &Path, source: &Path) -> Result<Vec<u8>, String> {
    if !converter.is_absolute() || !converter.is_file() {
        return Err("VECTORCRAFT_FH11_CONVERTER must point to the converter executable.".into());
    }
    #[cfg(windows)]
    if !converter.extension().and_then(|e| e.to_str()).is_some_and(|e| e.eq_ignore_ascii_case("exe")) {
        return Err("On Windows, select FreeHandImporter.exe as the converter.".into());
    }
    let metadata = fs::metadata(source).map_err(|e| e.to_string())?;
    if !metadata.is_file() || metadata.len() > LIMIT {
        return Err("Select a regular FreeHand file no larger than 512 MiB.".into());
    }
    let work = tempfile::Builder::new().prefix("vectorcraft-fh11-").tempdir().map_err(|e| e.to_string())?;
    let result = work.path().join("converted");
    let mut child = Command::new(converter)
        .arg("--convert")
        .arg(source)
        .arg("--out")
        .arg(&result)
        .env("VECTORCRAFT_NO_PREFS", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Couldn't start FreeHand Importer: {e}"))?;
    let started = Instant::now();
    loop {
        if cancel::is_cancelled() || started.elapsed() >= TIMEOUT {
            // The process may have exited just before the kill. Either way, reap it before
            // the temporary directory goes away.
            let _ = child.kill();
            let _ = child.wait();
            return Err(if cancel::is_cancelled() { "FreeHand import cancelled." } else { "FreeHand import timed out." }.into());
        }
        match child.try_wait() {
            Ok(Some(status)) if status.success() => break,
            Ok(Some(status)) => return Err(format!("FreeHand Importer failed ({status}). See its last error log for details.")),
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Couldn't wait for FreeHand Importer: {e}"));
            }
        }
    }
    let mut bytes = Vec::new();
    File::open(result.join("documento.vectorcraft"))
        .and_then(|f| f.take(LIMIT + 1).read_to_end(&mut bytes))
        .map_err(|e| format!("Couldn't read the converted VectorCraft document: {e}"))?;
    if bytes.len() as u64 > LIMIT {
        return Err("The converted VectorCraft document exceeds 512 MiB.".into());
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::matches;

    #[test]
    fn only_mx_drawings_use_the_local_converter() {
        assert!(matches("examples/Test.FH11"));
        assert!(matches("examples/test.fh11"));
        for other in ["test.fh", "test.fh10", "test.ft11", "test.fh11.vectorcraft", "test"] {
            assert!(!matches(other), "{other}");
        }
    }
}
