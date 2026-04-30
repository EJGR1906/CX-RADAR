namespace CXRadar.Bootstrapper;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new BootstrapperForm(new BootstrapperRunner()));
    }
}