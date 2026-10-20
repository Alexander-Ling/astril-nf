// Shared helpers for the "enter at any stage" data contract: given a dataset root that may be
// a flat collection of exam directories OR a nested {patient}/{exam}/... tree (or deeper), find
// the directories that actually contain the files a stage needs, rather than assuming one fixed
// nesting depth.
//
// Walks via plain java.io.File (isFile()/isDirectory()/listFiles() are File methods, not
// java.nio.file.Path ones), but returns java.nio.file.Path objects -- Nextflow's `path` process
// inputs reject a raw java.io.File ("Not a valid path value type"), so every result is
// converted back with .toPath() before being handed to a process.

def findLeafDirsContainingFile(java.io.File dir, String nameSubstring) {
    def here = dir.listFiles()
    if (here == null) {
        return []
    }
    def matches = here.findAll { it.isFile() && it.name.contains(nameSubstring) }
    if (matches) {
        return [dir]
    }
    return here
        .findAll { it.isDirectory() && it.name != '_raw_passthrough' }
        .collectMany { findLeafDirsContainingFile(it, nameSubstring) }
}

def findLeafDirsContaining(dir, String nameSubstring) {
    return findLeafDirsContainingFile(dir.toFile(), nameSubstring).collect { it.toPath() }
}
