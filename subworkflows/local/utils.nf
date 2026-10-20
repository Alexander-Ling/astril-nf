// Shared helpers for the "enter at any stage" data contract: given a dataset root that may be
// a flat collection of exam directories OR a nested {patient}/{exam}/... tree (or deeper), find
// the directories that actually contain the files a stage needs, rather than assuming one fixed
// nesting depth.
//
// Walks java.nio.file.Path objects via Nextflow's own Path extensions (listFiles(), isFile(),
// isDirectory(), name), NOT java.io.File: on Cirro/AWS Batch the workflow sees inputs as s3://
// paths, and Path.toFile() throws UnsupportedOperationException for anything that isn't on the
// default (local) filesystem. The same calls work unchanged on local paths.

def findLeafDirsContaining(dir, String nameSubstring) {
    def here = dir.listFiles()
    if (here == null) {
        return []
    }
    def matches = here.findAll { f -> f.isFile() && f.name.contains(nameSubstring) }
    if (matches) {
        return [dir]
    }
    return here
        .findAll { d -> d.isDirectory() && d.name != '_raw_passthrough' }
        .collectMany { d -> findLeafDirsContaining(d, nameSubstring) }
}
