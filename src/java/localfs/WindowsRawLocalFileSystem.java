package localfs;

import java.io.IOException;
import java.io.FileNotFoundException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import org.apache.hadoop.fs.FileStatus;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.RawLocalFileSystem;
import org.apache.hadoop.fs.permission.FsPermission;

/**
 * Local Hadoop filesystem for standalone Spark on Windows.
 *
 * Hadoop's default local filesystem delegates Unix permission changes to
 * winutils.exe. The project does not need POSIX permissions, HDFS or Hadoop
 * services, so this adapter uses Java NIO for directory creation and makes
 * permission/owner changes explicit no-ops.
 */
public final class WindowsRawLocalFileSystem extends RawLocalFileSystem {
    @Override
    public boolean mkdirs(Path path, FsPermission permission) throws IOException {
        Files.createDirectories(Paths.get(path.toUri()));
        return true;
    }

    @Override
    public void setPermission(Path path, FsPermission permission) {
        // Windows ACLs are managed by the operating system.
    }

    @Override
    public void setOwner(Path path, String username, String groupname) {
        // POSIX ownership is not applicable to this local Windows pipeline.
    }

    @Override
    public FileStatus[] listStatus(Path path) throws IOException {
        java.nio.file.Path nioPath = Paths.get(path.toUri());
        if (!Files.exists(nioPath)) {
            throw new FileNotFoundException(path.toString());
        }
        if (!Files.isDirectory(nioPath)) {
            return new FileStatus[] {getFileStatus(path)};
        }

        List<FileStatus> statuses = new ArrayList<>();
        try (Stream<java.nio.file.Path> children = Files.list(nioPath)) {
            for (java.nio.file.Path child : children.toList()) {
                statuses.add(getFileStatus(new Path(child.toUri())));
            }
        }
        return statuses.toArray(new FileStatus[0]);
    }
}
