import 'dart:math' as math;
import 'dart:ui';

/// Maps touch points (in the viewer's local coordinates) to normalized remote-screen coordinates,
/// accounting for letterboxing (contain-fit), zoom and pan.
class ViewGeometry {
  final Size view; // widget size
  final Size video; // remote frame size (any scale; only aspect matters)
  final double zoom; // >= 1
  final Offset pan; // translation applied after scaling (top-left origin)
  const ViewGeometry(this.view, this.video, {this.zoom = 1, this.pan = Offset.zero});

  /// The contain-fit rectangle of the video within the (unzoomed) view.
  Rect get fit {
    if (video.width <= 0 || video.height <= 0) return Offset.zero & view;
    final s = math.min(view.width / video.width, view.height / video.height);
    final w = video.width * s, h = video.height * s;
    return Rect.fromLTWH((view.width - w) / 2, (view.height - h) / 2, w, h);
  }

  /// local point -> normalized (0..1, clamped) position on the remote screen.
  Offset toNormalized(Offset local) {
    final c = (local - pan) / zoom;
    final r = fit;
    return Offset(((c.dx - r.left) / r.width).clamp(0.0, 1.0), ((c.dy - r.top) / r.height).clamp(0.0, 1.0));
  }

  /// normalized remote position -> local point (for drawing the cursor).
  Offset toLocal(Offset n) {
    final r = fit;
    return Offset(r.left + n.dx * r.width, r.top + n.dy * r.height) * zoom + pan;
  }

  /// Screen-pixels of finger movement -> remote pixels of cursor movement.
  double remotePerScreenPixel() => video.width <= 0 ? 1 : video.width / (fit.width * zoom);

  /// Keeps the zoomed content covering the view (no empty gaps at edges).
  Offset clampPan(Offset p, double z) {
    final minX = view.width - view.width * z, minY = view.height - view.height * z;
    return Offset(p.dx.clamp(math.min(0, minX), 0.0), p.dy.clamp(math.min(0, minY), 0.0));
  }

  ViewGeometry copyWith({double? zoom, Offset? pan}) =>
      ViewGeometry(view, video, zoom: zoom ?? this.zoom, pan: pan ?? this.pan);
}
